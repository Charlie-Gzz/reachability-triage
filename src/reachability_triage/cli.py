"""`rt` command line. Every Makefile target from Phase 0 is a subcommand here so it runs on Windows.

Heavy modules are imported inside each command so `rt --help` stays fast.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import config


def _targets(cfg: config.Config, names: list[str]) -> list[config.Target]:
    return cfg.targets if not names or names == ["all"] else [cfg.target(n) for n in names]


def _severity_bucket(score: str | None) -> str:
    if not score:
        return "unscored"
    s = float(score)
    return "critical" if s >= 9 else "high" if s >= 7 else "medium" if s >= 4 else "low"


def cmd_stats(_: argparse.Namespace | None = None) -> None:
    from .scan import osv
    rows = [json.loads(l) for l in osv.FINDINGS.read_text(encoding="utf-8").splitlines()]
    print(f"{'target':14}{'findings':>9}{'pkgs':>6}{'direct':>8}{'transit':>9}   severity")
    for name in sorted({r["target"] for r in rows}):
        fs = [r for r in rows if r["target"] == name]
        sev = Counter(_severity_bucket(r["max_cvss"]) for r in fs)
        direct = sum(r["direct_dependency"] for r in fs)
        print(f"{name:14}{len(fs):>9}{len({r['package'] for r in fs}):>6}{direct:>8}{len(fs) - direct:>9}   "
              + ", ".join(f"{k}={sev[k]}" for k in ("critical", "high", "medium", "low", "unscored") if sev[k]))
    print(f"{'TOTAL':14}{len(rows):>9}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="rt", description="Reachability triage for dependency vulnerabilities")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- Phase 0 (ported from the Makefile)
    sub.add_parser("tools", help="download the pinned osv-scanner binary")
    sub.add_parser("db", aliases=["build-db"], help="build the pinned offline PyPI advisory DB")
    sp = sub.add_parser("setup", help="clone targets at pinned commits and build their Docker images")
    sp.add_argument("targets", nargs="*", default=["all"])
    sp.add_argument("--rebuild", action="store_true")
    sp = sub.add_parser("verify-lock", help="diff each image's venv against the committed lock")
    sp.add_argument("targets", nargs="*", default=["all"])
    sp = sub.add_parser("baseline", help="run each unmodified test suite in its container")
    sp.add_argument("targets", nargs="*", default=["all"])
    sp = sub.add_parser("scan", help="scan runtime locks -> data/raw/*.osv.json + data/findings.jsonl")
    sp.add_argument("--online", action="store_true", help="query osv.dev instead of the pinned DB")
    sub.add_parser("stats", help="summarise data/findings.jsonl")
    sp = sub.add_parser("poetry-export", help="print pinned reqs for a poetry group (run in the project dir)")
    sp.add_argument("--group", default="main")
    sp.add_argument("--python", default="3.11")
    sp = sub.add_parser("import-names", help="record dist -> import-name maps from each target image")
    sp.add_argument("targets", nargs="*", default=["all"])

    # ---- Providers, RAG, agent
    sp = sub.add_parser("providers", help="check which LLM providers answer")
    sp.add_argument("--only", choices=["mock", "claude-code", "local"])
    sub.add_parser("bench", help="build bench findings from bench/cases and check them against the DB")
    sp = sub.add_parser("index", help="build the advisory and code indexes (Chroma + FAISS)")
    sp.add_argument("--rebuild", action="store_true")
    sub.add_parser("retrieval-check", help="recall@k and latency, Chroma vs FAISS")
    sp = sub.add_parser("triage", help="run the reachability agent")
    sp.add_argument("finding_ids", nargs="*")
    sp.add_argument("--all", action="store_true", help="every finding in the dataset/split")
    sp.add_argument("--config", default="dev-mock", help="name of eval/configs/<name>.yaml")
    sp.add_argument("--dataset", choices=["real", "bench", "eval-real", "all"], default=None)
    sp.add_argument("--split", choices=["dev", "test"], default=None)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--force", action="store_true", help="ignore the cache")
    sp = sub.add_parser("remediate", help="test-first remediation for reachable findings")
    sp.add_argument("finding_ids", nargs="*")
    sp.add_argument("--config", default="full")
    sp.add_argument("--max", type=int, default=10)
    sp.add_argument("--force", action="store_true")

    # ---- Labels, eval, outputs
    sp = sub.add_parser("sample", help="draw the stratified 50-finding real eval set")
    sp.add_argument("--n", type=int, default=50)
    sub.add_parser("draft-labels", help="draft real-set labels deterministically (no LLM)")
    sp = sub.add_parser("review", help="serve the label review page")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-browser", action="store_true")
    sub.add_parser("eval", help="compute metrics from cached runs (no LLM calls)")
    sub.add_parser("assets", help="charts, diagrams, screenshots -> assets/")
    sub.add_parser("site", help="build the static case explorer -> site/")
    sp = sub.add_parser("showcase", help="the full frozen eval, unattended and resumable")
    sp.add_argument("--skip-local", action="store_true")
    sub.add_parser("refresh", help="after reviewing labels: eval + assets + site")

    args = p.parse_args(argv)
    cfg = config.load()

    match args.cmd:
        case "tools":
            from .scan.tools import install_osv_scanner
            install_osv_scanner(cfg.osv_scanner_version)
        case "db" | "build-db":
            from .scan import advisory_db
            advisory_db.build(cfg.advisory_db)
        case "setup":
            from .scan import workspace
            for t in _targets(cfg, args.targets):
                workspace.setup(t, rebuild=args.rebuild)
        case "verify-lock":
            from .scan import workspace
            for t in _targets(cfg, args.targets):
                diff = workspace.verify_lock(t)
                print(f"{t.name}: {'matches committed lock' if not diff else 'DIFFERS: ' + ' '.join(diff)}")
        case "baseline":
            from .scan import workspace
            for t in _targets(cfg, args.targets):
                r = workspace.baseline(t)
                print(f"{t.name}: exit={r['exit_code']} passed={r['passed']} failed={r['failed']} ({r['seconds']}s)"
                      + (f" failing={r['failing_tests']}" if r["failing_tests"] else ""))
        case "scan":
            from .scan import advisory_db, osv, workspace
            if not args.online and not advisory_db.ZIP_PATH.exists():
                raise SystemExit("offline DB missing; run `rt db` (or pass --online)")
            findings = []
            for t in cfg.targets:
                workspace.checkout(t)
                findings += osv.normalise(t, osv.scan_target(cfg, t, online=args.online))
            osv.write_findings(findings)
            cmd_stats()
        case "stats":
            cmd_stats()
        case "poetry-export":
            from .scan.poetry_export import export
            print("\n".join(export(Path.cwd(), args.group, args.python)))
        case "import-names":
            from .scan import workspace
            out = config.DATA / "import_names"
            out.mkdir(parents=True, exist_ok=True)
            for t in _targets(cfg, args.targets):
                m = workspace.import_names(t)
                (out / f"{t.name}.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")
                print(f"{t.name}: {len(m)} distributions")
        case "providers":
            from .agent.providers import check_all
            check_all(args.only)
        case "bench":
            from .bench import build_findings
            build_findings()
        case "index":
            from .rag.indexes import build_all
            build_all(cfg, rebuild=args.rebuild)
        case "retrieval-check":
            from .rag.check import retrieval_check
            retrieval_check(cfg)
        case "triage":
            from .agent.runner import triage_cli
            triage_cli(cfg, args)
        case "remediate":
            from .remediate.pipeline import remediate_cli
            remediate_cli(cfg, args)
        case "sample":
            from .eval.sample import sample_real
            sample_real(args.n)
        case "draft-labels":
            from .eval.draft_labels import draft_all
            draft_all(cfg)
        case "review":
            from .review.server import serve
            serve(args.port, open_browser=not args.no_browser)
        case "eval":
            from .eval.metrics import run_eval
            run_eval()
        case "assets":
            from .outputs.assets import build_assets
            build_assets()
        case "site":
            from .outputs.site import build_site
            build_site()
        case "showcase":
            from .eval.showcase import showcase
            sys.exit(showcase(cfg, skip_local=args.skip_local))
        case "refresh":
            from .eval.metrics import run_eval
            from .outputs.assets import build_assets
            from .outputs.site import build_site
            run_eval()
            build_assets()
            build_site()


if __name__ == "__main__":
    main()
