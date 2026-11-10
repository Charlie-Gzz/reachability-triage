"""`rt showcase`: the whole frozen eval, unattended and resumable, in the plan's order.

1 full on bench test  2 full on the real eval set  3 ablations  4 remediation  5 local model.
Everything is cached per finding, so rerunning after a crash or a usage limit continues where it stopped.
"""
from __future__ import annotations

import time
from argparse import Namespace

from ..agent.providers import CLAUDE_CALL_CAP, claude_calls_used, discover_local
from ..agent.runner import load_run_config, run_triage, select
from ..config import Config

LOCAL_REAL_SUBSET = 20


# exit codes for `rt showcase`, so a wrapper can resume after a usage-limit reset
DONE, LIMIT, CAP = 0, 75, 3


def showcase(cfg: Config, skip_local: bool = False) -> int:
    t0 = time.time()
    calls0 = claude_calls_used()
    summary = []
    stages = [("full", "bench"), ("full", "eval-real"),
              ("no-retrieval", "bench"), ("no-retrieval", "eval-real"),
              ("no-reflection", "bench"), ("no-reflection", "eval-real")]
    stopped = False
    for config, dataset in stages:
        findings = select(dataset, "test" if dataset == "bench" else None, [])
        r = run_triage(cfg, load_run_config(config), findings)
        summary.append(f"{config:14} {dataset:10} {r['done']:>3} new, {r['cached']:>3} cached"
                       + (" STOPPED (usage limit)" if r["stopped"] else ""))
        if r["stopped"]:
            stopped = True
            break
    if not stopped:
        from ..remediate.pipeline import remediate_cli
        stopped = remediate_cli(cfg, Namespace(config="full", max=10, finding_ids=[], force=False))
        summary.append("remediation    " + ("STOPPED (usage limit)" if stopped else "done (see runs/full-remediation/)"))
    if not stopped and not skip_local:
        if discover_local():
            local = load_run_config("local")
            bench = select("bench", "test", [])
            real = select("eval-real", None, [])[:LOCAL_REAL_SUBSET]
            r = run_triage(cfg, local, bench + real)
            summary.append(f"local          bench+{LOCAL_REAL_SUBSET} real {r['done']:>3} new, {r['cached']:>3} cached")
        else:
            summary.append("local          skipped: no local model endpoint answering")
    from .metrics import run_eval
    run_eval(quiet=True)
    print("\n=== showcase summary ===")
    print("\n".join(summary))
    print(f"Claude calls this run: {claude_calls_used() - calls0} (total {claude_calls_used()} of 1500)")
    print(f"elapsed: {(time.time() - t0) / 60:.1f} min.  Next: `rt refresh` (eval + assets + site).")
    if not stopped:
        return DONE
    return CAP if claude_calls_used() >= CLAUDE_CALL_CAP else LIMIT
