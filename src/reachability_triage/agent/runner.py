"""Run the agent over findings with an on-disk cache: runs/<config>/<finding>.json.

A rerun skips findings that already have a record, so runs resume after a crash or a usage limit,
and the committed runs reproduce every number and chart without any LLM calls.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..config import DATA, EVAL, RUNS, Config
from .providers import UsageLimitError, make

CONFIG_DIR = EVAL / "configs"


def load_run_config(name: str) -> dict:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"no config {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["name"] = name
    return cfg


def record_path(config: str, finding_id: str) -> Path:
    return RUNS / config / (finding_id.replace("/", "__") + ".json")


def load_record(config: str, finding_id: str) -> dict | None:
    p = record_path(config, finding_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ datasets

def real_findings() -> list[dict]:
    return [json.loads(l) for l in (DATA / "findings.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def eval_real_ids() -> list[str]:
    p = DATA / "eval_set.json"
    return json.loads(p.read_text(encoding="utf-8"))["finding_ids"] if p.exists() else []


def select(dataset: str | None, split: str | None, ids: list[str]) -> list[dict]:
    from ..bench import bench_findings
    pool = real_findings() + bench_findings()
    if ids:
        by = {f["finding_id"]: f for f in pool}
        missing = [i for i in ids if i not in by]
        if missing:
            raise SystemExit(f"unknown finding ids: {missing}")
        return [by[i] for i in ids]
    if dataset == "real":
        return real_findings()
    if dataset == "eval-real":
        keep = set(eval_real_ids())
        return [f for f in real_findings() if f["finding_id"] in keep]
    if dataset == "bench":
        return [f for f in bench_findings() if not split or f.get("split") == split]
    if dataset == "all":
        return pool
    raise SystemExit("pass finding ids, or --all with --dataset")


def codebase_for(cfg: Config, finding: dict) -> dict:
    from ..config import BENCH
    from .advisory import import_names_for
    target = finding["target"]
    if target.startswith("bench/"):
        root = BENCH / "cases" / target.split("/", 1)[1]
        return {"name": target, "root": root, "app_dirs": [], "test_dirs": ["tests"], "template_dirs": ["."],
                "import_names": import_names_for(finding["package"], None)}
    t = cfg.target(target)
    return {"name": t.name, "root": t.checkout, "app_dirs": t.app_dirs, "test_dirs": t.test_dirs,
            "template_dirs": t.template_dirs, "import_names": import_names_for(finding["package"], t.name)}


# ------------------------------------------------------------------ running

def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def triage_one(cfg: Config, run_cfg: dict, finding: dict, graph) -> dict:
    cb = codebase_for(cfg, finding)
    t = time.perf_counter()
    state = graph.invoke({"finding": finding, "codebase": cb, "steps": [], "errors": [],
                          "options": {"retrieval": run_cfg.get("retrieval", True),
                                      "reflection": run_cfg.get("reflection", True),
                                      "max_retries": run_cfg.get("max_retries", 1)}})
    steps = state["steps"]
    rec = {
        "finding_id": finding["finding_id"], "config": run_cfg["name"],
        "dataset": "bench" if finding["target"].startswith("bench/") else "real",
        "split": finding.get("split"), "target": finding["target"],
        "provider": run_cfg["provider"]["provider"], "model": run_cfg["provider"].get("model", ""),
        "options": {k: run_cfg.get(k) for k in ("retrieval", "reflection", "store")},
        "finding": finding, "final": state["final"], "verdict": state["verdict"],
        "reflection": state.get("reflection"), "symbols": state.get("symbols", []), "errors": state.get("errors", []),
        "steps": steps,
        "totals": {"llm_calls": sum(s["llm_calls"] for s in steps), "tokens_in": sum(s["tokens_in"] for s in steps),
                   "tokens_out": sum(s["tokens_out"] for s in steps),
                   "cost_usd_est": round(sum(s["cost_usd_est"] for s in steps), 6),
                   "seconds": round(time.perf_counter() - t, 2)},
        "created": datetime.now(UTC).isoformat(timespec="seconds"), "code_version": _git_sha(),
    }
    p = record_path(run_cfg["name"], finding["finding_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return rec


def run_triage(cfg: Config, run_cfg: dict, findings: list[dict], force: bool = False) -> dict:
    from .graph import build_graph
    retriever = None
    if run_cfg.get("retrieval", True):
        from ..rag.indexes import Retriever
        retriever = Retriever(run_cfg.get("store", "chroma"))
    provider = make(run_cfg["provider"], label=run_cfg["name"])
    graph = build_graph(provider, retriever)
    done = skipped = 0
    stopped = None
    for i, f in enumerate(findings, 1):
        if not force and record_path(run_cfg["name"], f["finding_id"]).exists():
            skipped += 1
            continue
        try:
            rec = triage_one(cfg, run_cfg, f, graph)
        except UsageLimitError as e:
            stopped = str(e)[:300]
            print(f"\nSTOPPED on usage/credit limit after {done} findings: {stopped}", file=sys.stderr)
            _log_progress(f"`{run_cfg['name']}` stopped on a usage/credit limit after {done} new findings "
                          f"({skipped} cached). Rerun the same command to resume.")
            break
        done += 1
        fin = rec["final"]
        print(f"[{i}/{len(findings)}] {f['finding_id']}: {fin['verdict']} ({fin['confidence']:.2f})"
              f"  {rec['totals']['llm_calls']} calls, {rec['totals']['seconds']}s", file=sys.stderr)
    return {"done": done, "cached": skipped, "stopped": stopped}


def _log_progress(line: str) -> None:
    from ..config import DOCS
    p = DOCS / "PROGRESS.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"- {stamp}: {line}\n")


def triage_cli(cfg: Config, args) -> None:
    run_cfg = load_run_config(args.config)
    if args.all:
        findings = select(args.dataset or "all", args.split, [])
    else:
        findings = select(None, None, args.finding_ids)
    if args.limit:
        findings = findings[:args.limit]
    r = run_triage(cfg, run_cfg, findings, force=args.force)
    print(f"{run_cfg['name']}: {r['done']} run, {r['cached']} cached" + (f", STOPPED: {r['stopped']}" if r["stopped"] else ""))
