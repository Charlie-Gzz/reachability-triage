"""Test-first remediation for findings the agent marked reachable.

failing test (LLM) -> must be RED in a throwaway container -> fix: upgrade to the fixed version
(patch app code only if the upgrade breaks the suite) -> gate: new test GREEN and the suite has no
failures beyond the container baseline. Each attempt runs in a fresh git worktree + fresh container.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .. import sandbox
from ..agent import advisory
from ..agent.providers import UsageLimitError, make, structured
from ..agent.runner import load_record, load_run_config, real_findings, record_path
from ..agent.schemas import GeneratedTest, Patch
from ..config import DATA, LOCKS, RUNS, Config, Target
from ..scan import workspace
from ..scan.workspace import failing_tests, parse_test_summary

DOS_CWES = {"CWE-400", "CWE-1333", "CWE-770", "CWE-674", "CWE-835", "CWE-407", "CWE-409", "CWE-1050", "CWE-834"}
TEST_TIMEOUT = 900
MAX_TEST_TRIES = 2
MAX_FIX_TRIES = 2

TEST_SYSTEM = """You write a single regression test that proves a dependency vulnerability affects an application.
The test must exercise the vulnerable behaviour THROUGH THE APPLICATION'S OWN CODE PATH (its function, view, or
endpoint), not by calling the library directly unless the app calls it the same way. It must FAIL on the installed
(vulnerable) version and PASS once the dependency is upgraded to the fixed version. Assert on the security-relevant
behaviour (e.g. the escaped output, the rejected input, the stripped header), with a clear assertion message.
Use only the test tooling the project already uses. No network access. Keep it short and deterministic."""

PATCH_SYSTEM = """Upgrading the vulnerable dependency could not be accepted (it broke the suite or did not fix the
behaviour), so write the smallest change
to the APPLICATION code that removes the vulnerable behaviour (e.g. validate or escape input before it reaches the
vulnerable function, or stop using the vulnerable option). Do not modify tests. Return full new contents for each
changed file."""


def _result(out: str) -> dict:
    s = parse_test_summary(out)
    return {**s, "failing": failing_tests(out)}


def _tail(text: str, n: int = 3500) -> str:
    return text[-n:]


def _baseline_failures(t: Target) -> set[str]:
    p = DATA / "baselines" / "container" / f"{t.name}.json"
    return set(json.loads(p.read_text(encoding="utf-8"))["failing_tests"]) if p.exists() else set()


def _test_context(t: Target, rec: dict) -> str:
    """A small, real slice of the project's test conventions: test runner, an existing test, fixtures."""
    root = t.checkout
    candidates = []
    for d in t.test_dirs:
        candidates += sorted((root / d).rglob("test_*.py"))[:200]
    cited = {s["file"] for s in rec["steps"][2]["output"]["vulnerable_call_sites"] if not s["in_test"]}
    stem_hits = [p for p in candidates if any(Path(c).stem.split("_")[0] in p.stem for c in cited)]
    example = (stem_hits or candidates)[:1]
    parts = [f"Test command: {t.test_cmd}  (framework: {t.framework}, python {t.python})"]
    for conf in list(root.glob("tests/conftest.py"))[:1] + list(root.glob("conftest.py"))[:1]:
        parts.append(f"## {conf.relative_to(root).as_posix()} (first 80 lines)\n" +
                     "\n".join(conf.read_text(encoding="utf-8", errors="replace").splitlines()[:80]))
    for p in example:
        parts.append(f"## Example existing test: {p.relative_to(root).as_posix()} (first 70 lines)\n" +
                     "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:70]))
    if t.framework == "flask":
        helpers = root / "tests" / "helpers.py"
        if helpers.exists():
            names = re.findall(r"^def (\w+)\(", helpers.read_text(encoding="utf-8", errors="replace"), re.M)
            parts.append("tests/helpers.py defines: " + ", ".join(names[:40]))
    return "\n\n".join(parts)


def _evidence_text(rec: dict) -> str:
    ev = rec["steps"][2]["output"]
    lines = [ev["summary"]]
    for s in ev["vulnerable_call_sites"][:6]:
        if not s["in_test"]:
            lines.append(f"- {s['file']}:{s['line']} in {s['function']}: {s['code']}\n{s.get('snippet', '')}")
    lines.append("Verdict reasoning: " + rec["verdict"].get("reasoning", ""))
    return "\n".join(lines)


def candidates(config: str, limit: int) -> list[dict]:
    """Reachable real findings from a triage run, most realistic-to-test first."""
    findings = {f["finding_id"]: f for f in real_findings()}
    pool = []
    for p in sorted((RUNS / config).glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r["dataset"] != "real" or r["final"]["verdict"] != "reachable":
            continue
        f = findings[r["finding_id"]]
        fix = f.get("first_fixed_above_installed")
        if not fix:
            continue
        same_major = fix.split(".")[0] == f["version"].split(".")[0]
        dos = bool(set(f.get("cwes", [])) & DOS_CWES)
        score = (2 * same_major) + (1 if f["direct_dependency"] else 0) - (2 if dos else 0) + r["final"]["confidence"]
        pool.append((score, f, r))
    pool.sort(key=lambda x: -x[0])
    return [(f, r) for _, f, r in pool[:limit]]


def _lock_diff(t: Target, package: str, old: str, new: str) -> str:
    lock = LOCKS / f"{t.name}.runtime.txt"
    before = lock.read_text(encoding="utf-8").splitlines(keepends=True)
    pat = re.compile(rf"^{re.escape(package)}==", re.I)
    after = [re.sub(rf"=={re.escape(old)}\b", f"=={new}", l) if pat.match(re.sub(r"[-_.]+", "-", l)) else l for l in before]
    return "".join(difflib.unified_diff(before, after, f"a/locks/{lock.name}", f"b/locks/{lock.name}"))


def remediate_one(cfg: Config, provider, f: dict, rec: dict, out_dir: Path) -> dict:
    t = cfg.target(f["target"])
    recs = advisory.for_finding(f)
    adv = "\n\n".join(f"{r['id']}: {r.get('summary', '')}\n{(r.get('details') or '')[:3000]}" for r in recs[:2])
    fix = f["first_fixed_above_installed"]
    steps: list[dict] = []
    result = {"finding_id": f["finding_id"], "target": t.name, "package": f["package"], "from": f["version"], "to": fix,
              "status": "failed", "reason": None, "steps": steps, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0}
    base_fail = _baseline_failures(t)

    def log(node: str, start: float, **kw):
        steps.append({"node": node, "ms": round((time.perf_counter() - start) * 1000), **kw})

    # ---------------- 1. failing test (must be RED on the vulnerable version)
    feedback, test = "", None
    for attempt in range(1, MAX_TEST_TRIES + 1):
        st = time.perf_counter()
        prompt = (f"## Vulnerability\n{f['package']}=={f['version']} is vulnerable; fixed in {fix}.\n{adv}\n\n"
                  f"## Why the agent marked it reachable in this app\n{_evidence_text(rec)}\n\n"
                  f"## Project test conventions\n{_test_context(t, rec)}\n\n"
                  f"Write the new test file. Put it under {t.test_dirs[0]}/ with a name starting test_rt_. "
                  + ("test_id must be a dotted Django test label (module.Class.method)." if t.framework == "django"
                     else "test_id must be a pytest node id (path::test_name).") + feedback)
        obj, meta, err = structured(provider, TEST_SYSTEM, prompt, GeneratedTest, task="test")
        result["llm_calls"] += meta.calls
        result["tokens_in"] += meta.input_tokens
        result["tokens_out"] += meta.output_tokens
        if obj is None:
            log("write_test", st, attempt=attempt, error=err)
            continue
        wt = workspace.worktree(t, f"{_slug(f)}-red{attempt}")
        try:
            (wt / obj.test_path).parent.mkdir(parents=True, exist_ok=True)
            (wt / obj.test_path).write_text(obj.code, encoding="utf-8", newline="\n")
            r = sandbox.run_tests(t, wt, [obj.test_id], timeout=TEST_TIMEOUT)
        finally:
            workspace.remove_worktree(t, wt)
        res = _result(r.output)
        red = res["failed"] > 0 and res["passed"] == 0
        kind = "timeout" if r.timed_out else ("red" if red and not _collection_error(r.output) else
                                              ("passes_before_fix" if res["passed"] and not res["failed"] else "error"))
        log("write_test", st, attempt=attempt, test_path=obj.test_path, test_id=obj.test_id, code=obj.code,
            rationale=obj.rationale, run={"outcome": kind, **res, "seconds": r.seconds, "output": _tail(r.output)})
        if kind == "red":
            test = obj
            break
        feedback = (f"\n\n## Your previous test did not fail correctly ({kind}). Output:\n{_tail(r.output, 2500)}\n"
                    "Fix it so it fails ONLY because of the vulnerable behaviour.")
    if test is None:
        result["reason"] = "no_failing_test"
        return result

    # ---------------- 2. fix: upgrade first
    pip = f'uv pip install -q -p $PY "{f["package"]}=={fix}"'
    st = time.perf_counter()
    wt = workspace.worktree(t, f"{_slug(f)}-upgrade")
    try:
        (wt / test.test_path).parent.mkdir(parents=True, exist_ok=True)
        (wt / test.test_path).write_text(test.code, encoding="utf-8", newline="\n")
        new = sandbox.run_tests(t, wt, [test.test_id], setup=[pip], timeout=TEST_TIMEOUT)
        suite = (sandbox.run_tests(t, wt, None, setup=[pip, PIP_CHECK], timeout=TEST_TIMEOUT)
                 if not new.timed_out else new)
    finally:
        workspace.remove_worktree(t, wt)
    new_res, suite_res = _result(new.output), _result(suite.output)
    new_green = new_res["passed"] > 0 and new_res["failed"] == 0 and not new.timed_out
    regressions = _regressions(suite_res, base_fail, test.test_id)
    conflict = CONFLICT_MARK in suite.output       # e.g. requests pins urllib3<1.27 but the upgrade installs 2.x
    suite_ok = not suite.timed_out and not regressions and suite_res["passed"] > 0 and not conflict
    log("apply_fix", st, kind="upgrade", command=pip, dependency_conflict=conflict, diff=_lock_diff(t, f["package"], f["version"], fix),
        new_test={**new_res, "seconds": new.seconds, "output": _tail(new.output)},
        suite={**{k: suite_res[k] for k in ("passed", "failed")}, "regressions": regressions[:20],
               "seconds": suite.seconds, "timed_out": suite.timed_out, "output": _tail(suite.output, 2000)})
    if new_green and suite_ok:
        result.update(status="fixed", reason=None, fix_kind="upgrade",
                      diff=_lock_diff(t, f["package"], f["version"], fix), test=test.model_dump())
        return result
    if suite.timed_out or new.timed_out:
        result["reason"] = "timeout"
    elif not new_green:
        result["reason"] = "upgrade_did_not_turn_test_green"
    elif conflict:
        result["reason"] = "upgrade_breaks_dependency_pins"
    else:
        result["reason"] = "upgrade_broke_suite"

    # ---------------- 3. code patch (only when the upgrade can't be accepted)
    if result["reason"] == "timeout":
        result["test"] = test.model_dump()
        return result
    feedback = ""
    for attempt in range(1, MAX_FIX_TRIES + 1):
        st = time.perf_counter()
        files = {s["file"] for s in rec["steps"][2]["output"]["vulnerable_call_sites"] if not s["in_test"]}
        src = "\n\n".join(f"## {p}\n```python\n{(t.checkout / p).read_text(encoding='utf-8', errors='replace')[:6000]}\n```"
                          for p in sorted(files)[:3])
        prompt = (f"## Vulnerability\n{adv[:3000]}\n\n## Failing regression test ({test.test_path})\n```python\n{test.code}\n```"
                  f"\n\n## Why the upgrade to {fix} was rejected\n{result['reason']}; suite regressions: "
                  f"{', '.join(regressions[:15]) or 'none'}; new test after upgrade: {new_res['passed']} passed, "
                  f"{new_res['failed']} failed\n\n"
                  f"## Application files on the vulnerable path\n{src}{feedback}")
        obj, meta, err = structured(provider, PATCH_SYSTEM, prompt, Patch, task="patch")
        result["llm_calls"] += meta.calls
        result["tokens_in"] += meta.input_tokens
        result["tokens_out"] += meta.output_tokens
        if obj is None or not obj.files:
            log("apply_fix", st, kind="patch", attempt=attempt, error=err or "empty patch")
            continue
        wt = workspace.worktree(t, f"{_slug(f)}-patch{attempt}")
        try:
            diff = ""
            for fe in obj.files:
                p = wt / fe.path
                before = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.exists() else []
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(fe.content, encoding="utf-8", newline="\n")
                diff += "".join(difflib.unified_diff(before, fe.content.splitlines(keepends=True),
                                                     f"a/{fe.path}", f"b/{fe.path}"))
            (wt / test.test_path).parent.mkdir(parents=True, exist_ok=True)
            (wt / test.test_path).write_text(test.code, encoding="utf-8", newline="\n")
            new = sandbox.run_tests(t, wt, [test.test_id], timeout=TEST_TIMEOUT)
            suite = sandbox.run_tests(t, wt, None, timeout=TEST_TIMEOUT)
        finally:
            workspace.remove_worktree(t, wt)
        new_res, suite_res = _result(new.output), _result(suite.output)
        regressions = _regressions(suite_res, base_fail, test.test_id)
        ok = new_res["passed"] > 0 and new_res["failed"] == 0 and not regressions and not suite.timed_out
        log("apply_fix", st, kind="patch", attempt=attempt, diff=diff, rationale=obj.rationale,
            new_test={**new_res, "output": _tail(new.output)},
            suite={"passed": suite_res["passed"], "failed": suite_res["failed"], "regressions": regressions[:20],
                   "output": _tail(suite.output, 2000)})
        if ok:
            result.update(status="fixed", reason=None, fix_kind="patch", diff=diff, test=test.model_dump())
            return result
        feedback = f"\n\n## Previous patch failed\nnew test: {new_res}\nregressions: {regressions[:10]}\n{_tail(new.output, 1500)}"
    result.update(reason="patch_failed", test=test.model_dump())
    return result


# Gate: the upgraded environment must still satisfy every installed package's declared requirements.
# Every target image passes `uv pip check` at baseline (checked 2026-11-10), so any conflict is the upgrade's.
CONFLICT_MARK = "RT_DEPENDENCY_CONFLICT"
PIP_CHECK = f"uv pip check -p $PY || echo {CONFLICT_MARK}"


def _regressions(suite_res: dict, base_fail: set[str], new_test: str) -> list[str]:
    """Failures beyond the container baseline. Falls back to counts when failures can't be parsed into ids."""
    regs = sorted(set(suite_res["failing"]) - base_fail - {new_test})
    unexplained = suite_res["failed"] - len(base_fail) - len(regs) - (1 if new_test in suite_res["failing"] else 0)
    if unexplained > 0:
        regs.append(f"<{unexplained} more failures/errors without test ids>")
    return regs


def _collection_error(out: str) -> bool:
    return bool(re.search(r"ERROR collecting|ImportError|ModuleNotFoundError|SyntaxError|fixture '.+' not found|"
                          r"^ERROR: |Traceback \(most recent call last\):\s+File \"/app/manage.py\"", out, re.M)) and \
        not re.search(r"AssertionError", out)


def _slug(f: dict) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", f"{f['package']}-{f['vuln_id']}")[:60]


def remediate_cli(cfg: Config, args) -> bool:
    """Returns True if it stopped on a usage/credit limit (rerun to resume)."""
    run_cfg = load_run_config(args.config)
    provider = make(run_cfg["provider"], label=f"{run_cfg['name']}-remediation")
    out_dir = RUNS / f"{run_cfg['name']}-remediation"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.finding_ids:
        by = {f["finding_id"]: f for f in real_findings()}
        pairs = [(by[i], load_record(run_cfg["name"], i)) for i in args.finding_ids]
    else:
        pairs = candidates(run_cfg["name"], args.max)
    print(f"{len(pairs)} remediation candidates", file=sys.stderr)
    for f, rec in pairs:
        path = out_dir / (f["finding_id"].replace("/", "__") + ".json")
        if path.exists() and not args.force:
            print(f"cached  {f['finding_id']}", file=sys.stderr)
            continue
        if rec is None:
            print(f"skip {f['finding_id']}: no triage record in {record_path(run_cfg['name'], f['finding_id'])}")
            continue
        st = time.perf_counter()
        try:
            res = remediate_one(cfg, provider, f, rec, out_dir)
        except UsageLimitError as e:
            print(f"STOPPED on usage/credit limit: {str(e)[:200]}", file=sys.stderr)
            from ..agent.runner import _log_progress
            _log_progress("remediation stopped on a usage/credit limit; rerun `rt remediate` to resume")
            return True
        res["seconds"] = round(time.perf_counter() - st, 1)
        res["created"] = datetime.now(UTC).isoformat(timespec="seconds")
        path.write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
        print(f"{res['status']:7} {f['finding_id']}  {res.get('reason') or res.get('fix_kind')}  ({res['seconds']}s)")
    return False
