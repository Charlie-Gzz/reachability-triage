"""Stratified sample of the real findings for evaluation.

Method (logged in DECISIONS.md): allocate the sample across targets proportionally to their finding
counts with a floor of 10 per target, then within each target allocate across severity buckets
proportionally (largest-remainder rounding), and draw uniformly at random with a fixed seed.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict

from ..config import DATA

SEED = 20261109


def _bucket(score):
    if not score:
        return "unscored"
    s = float(score)
    return "critical" if s >= 9 else "high" if s >= 7 else "medium" if s >= 4 else "low"


def _alloc(sizes: dict[str, int], n: int, floor: int = 0) -> dict[str, int]:
    total = sum(sizes.values())
    base = {k: max(min(floor, v), int(n * v / total)) for k, v in sizes.items()}
    rema = sorted(sizes, key=lambda k: -(n * sizes[k] / total - int(n * sizes[k] / total)))
    i = 0
    while sum(base.values()) < n:
        k = rema[i % len(rema)]
        if base[k] < sizes[k]:
            base[k] += 1
        i += 1
    while sum(base.values()) > n:
        k = max(base, key=lambda k: base[k])
        base[k] -= 1
    return base


def sample_real(n: int = 50) -> list[str]:
    from ..agent.runner import real_findings
    rows = real_findings()
    by_target = defaultdict(list)
    for r in rows:
        by_target[r["target"]].append(r)
    per_target = _alloc({t: len(v) for t, v in by_target.items()}, n, floor=10)
    rng = random.Random(SEED)
    chosen, plan = [], {}
    for t in sorted(by_target):
        strata = defaultdict(list)
        for r in sorted(by_target[t], key=lambda r: r["finding_id"]):
            strata[_bucket(r["max_cvss"])].append(r)
        alloc = _alloc({b: len(v) for b, v in strata.items()}, per_target[t])
        plan[t] = alloc
        for b, k in sorted(alloc.items()):
            chosen += [r["finding_id"] for r in rng.sample(strata[b], k)]
    out = {"method": "proportional by target (floor 10), then proportional by CVSS severity bucket within target, "
                     f"uniform random within strata, seed {SEED}", "n": len(chosen), "allocation": plan,
           "finding_ids": sorted(chosen)}
    (DATA / "eval_set.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: out[k] for k in ("n", "allocation")}, indent=1))
    return chosen
