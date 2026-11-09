"""Check out targets at their pinned commits, build their images, freeze locks, run baselines.

The checkout lives on the Windows host (workdirs/<name>) because static analysis and the
code index read it from disk. Everything that executes target code runs in the target's
container (see sandbox.py).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .. import sandbox
from ..config import DATA, WORKDIRS, Target
from ..shell import run


def _git(*args: str, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
    # Never let Git for Windows rewrite line endings: these files are run inside Linux containers.
    return run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, capture=capture)


def checkout(t: Target) -> None:
    """Shallow-fetch exactly the pinned commit. Refuses to proceed if HEAD doesn't match."""
    d = t.checkout
    if not (d / ".git").exists():
        d.mkdir(parents=True, exist_ok=True)
        _git("init", "-q", cwd=d)
        _git("config", "core.autocrlf", "false", cwd=d)
        _git("remote", "add", "origin", t.url, cwd=d)
        _git("fetch", "-q", "--depth", "1", "origin", t.commit, cwd=d)
        _git("checkout", "-q", "FETCH_HEAD", cwd=d)
    head = _git("rev-parse", "HEAD", cwd=d, capture=True).stdout.strip()
    if head != t.commit:
        raise SystemExit(f"{t.name}: checkout is at {head}, expected {t.commit}")


def worktree(t: Target, name: str) -> Path:
    """A fresh, clean git worktree of the target for one remediation attempt."""
    path = WORKDIRS / "_worktrees" / t.name / name
    if path.exists():
        _git("worktree", "remove", "--force", str(path), cwd=t.checkout)
    path.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-q", "--detach", str(path), t.commit, cwd=t.checkout)
    return path


def remove_worktree(t: Target, path: Path) -> None:
    _git("worktree", "remove", "--force", str(path), cwd=t.checkout)


def setup(t: Target, rebuild: bool = False) -> None:
    """Clone at the pinned commit and build the target image from the committed lock."""
    checkout(t)
    if rebuild or not sandbox.image_exists(t):
        sandbox.build_image(t)
    else:
        print(f"{t.name}: image {t.image} already built (use --rebuild to force)", file=sys.stderr)


def verify_lock(t: Target) -> list[str]:
    """Freeze the image's venv and diff it against the committed test-env lock."""
    frozen = sandbox.py(t, "import importlib.metadata as m;"
                           "print('\\n'.join(sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions())))")
    have = {l.lower().replace("_", "-") for l in frozen.split() if "==" in l}
    want = {l.strip().lower().replace("_", "-") for l in t.test_lockfile.read_text().splitlines()
            if "==" in l and not l.startswith("#")}
    return sorted(f"-{x}" for x in want - have) + sorted(f"+{x}" for x in have - want)


def import_names(t: Target) -> dict[str, list[str]]:
    """{distribution: [top-level import names]} from the target's venv, for static analysis."""
    code = r"""
import importlib.metadata as m, json, re
out = {}
for d in m.distributions():
    name = re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower()
    tops = set()
    txt = d.read_text("top_level.txt")
    if txt:
        tops |= {l.strip() for l in txt.split() if l.strip()}
    for f in (d.files or []):
        p = str(f).split("/")
        if p[0].endswith((".dist-info", ".egg-info", ".data")) or p[0] in ("..", "bin", "__pycache__"):
            continue
        if len(p) > 1 or p[0].endswith(".py"):
            tops.add(p[0].removesuffix(".py"))
    out[name] = sorted(x for x in tops if x.isidentifier() and not x.startswith("_"))
print(json.dumps(out, sort_keys=True))
"""
    return json.loads(sandbox.py(t, code))


_PYTEST = re.compile(r"(\d+) (passed|failed|errors?|skipped)")
_DJANGO_RAN = re.compile(r"^Ran (\d+) tests?", re.M)
_DJANGO_BAD = re.compile(r"(failures|errors)=(\d+)")


def parse_test_summary(output: str) -> dict:
    """Pull pass/fail counts out of pytest or Django test-runner output."""
    if m := _DJANGO_RAN.search(output):
        bad = {k: int(v) for k, v in _DJANGO_BAD.findall(output)}
        failed = bad.get("failures", 0) + bad.get("errors", 0)
        return {"runner": "django", "total": int(m.group(1)), "failed": failed,
                "passed": int(m.group(1)) - failed}
    counts: dict[str, int] = {}
    for n, kind in _PYTEST.findall(output):
        counts["errors" if kind.startswith("error") else kind] = int(n)
    return {"runner": "pytest", "passed": counts.get("passed", 0),
            "failed": counts.get("failed", 0) + counts.get("errors", 0),
            "skipped": counts.get("skipped", 0)}


_DJANGO_FAIL = re.compile(r"^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", re.M)


def failing_tests(output: str) -> list[str]:
    ids = set(re.findall(r"^(?:FAILED|ERROR) (\S+::\S+)", output, re.M))
    ids |= {f"{cls}.{meth}" for meth, cls in _DJANGO_FAIL.findall(output)}
    return sorted(ids)


def baseline(t: Target, out_dir: Path = DATA / "baselines" / "container") -> dict:
    """Run the unmodified suite once in the container. The remediation gate compares against this."""
    checkout(t)
    r = sandbox.run_tests(t, t.checkout, timeout=1800)
    result = {
        "target": t.name, "commit": t.commit, "cmd": t.test_cmd, "image": t.image,
        "exit_code": r.exit_code, "seconds": r.seconds, "timed_out": r.timed_out,
        **parse_test_summary(r.output),
        "failing_tests": failing_tests(r.output),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{t.name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{t.name}.log").write_text(r.output[-200_000:], encoding="utf-8")
    return result
