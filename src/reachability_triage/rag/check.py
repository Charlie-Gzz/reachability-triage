"""Retrieval quality check: does the right advisory / code chunk land in the top-k? Chroma vs FAISS.

Advisory: query = "<package>: <scanner summary>" against the whole advisory index (no id filter);
          hit = any chunk of the finding's own advisory (any alias) in the top k.
Code:     query = what the agent uses (package + advisory symbols + summary) against that codebase's chunks;
          hit = a chunk whose line span covers the known vulnerable location (bench ground truth).
"""
from __future__ import annotations

import json
import statistics

from ..agent import advisory
from ..bench import bench_cases, bench_findings
from ..config import DATA, EVAL, Config
from .indexes import ADVISORY_COLLECTION, CODE_COLLECTION
from .store import embedder, open_store, timed_search

KS = (1, 3, 5, 10)


def _recall(ranks: list[int | None]) -> dict:
    n = len(ranks)
    out = {f"recall@{k}": round(sum(1 for r in ranks if r is not None and r < k) / n, 3) for k in KS}
    out["mrr"] = round(sum(1 / (r + 1) for r in ranks if r is not None) / n, 3)
    out["n"] = n
    return out


def retrieval_check(cfg: Config) -> dict:
    from ..agent.runner import real_findings
    emb = embedder()
    stores = {k: (open_store(k, ADVISORY_COLLECTION), open_store(k, CODE_COLLECTION)) for k in ("chroma", "faiss")}
    results: dict = {"embed_model": emb.name}

    # -------- advisory retrieval
    findings = bench_findings() + real_findings()
    adv_q = [(f, emb.query(f"{f['package']}: {f.get('summary', '')}")) for f in findings]
    for kind, (adv, _) in stores.items():
        ranks, lat = [], []
        for f, q in adv_q:
            own = {f["vuln_id"], *f.get("aliases", [])}
            hits, ms = timed_search(adv, q, k=max(KS))
            lat.append(ms)
            ranks.append(next((i for i, h in enumerate(hits) if h.meta["vuln_id"] in own
                               or own & set(h.meta.get("aliases", "").split())), None))
        results.setdefault("advisory", {})[kind] = {**_recall(ranks), "latency_ms_p50": round(statistics.median(lat), 2),
                                                    "latency_ms_p95": round(sorted(lat)[int(len(lat) * .95) - 1], 2),
                                                    "index_size": adv.count()}

    # -------- code retrieval (bench cases with a known vulnerable .py location)
    cases = {c["case"]: c for c in bench_cases()}
    code_items = []
    for f in bench_findings():
        c = cases[f["target"].split("/", 1)[1]]
        if not c["evidence"] or not c["evidence"].split(":")[0].endswith(".py"):
            continue
        file, line = c["evidence"].rsplit(":", 1)
        syms = advisory.symbols_for(f, advisory.for_finding(f), advisory.import_names_for(f["package"], None))
        q = f"{f['package']} {' '.join(syms[:5])} {f.get('summary', '')}"
        code_items.append((f, file, int(line), emb.query(q)))
    for kind, (_, code) in stores.items():
        ranks, lat = [], []
        for f, file, line, q in code_items:
            hits, ms = timed_search(code, q, k=max(KS), where={"codebase": f["target"]})
            lat.append(ms)
            ranks.append(next((i for i, h in enumerate(hits) if h.meta["file"] == file
                               and h.meta["start"] <= line <= h.meta["end"]), None))
        results.setdefault("code", {})[kind] = {**_recall(ranks), "latency_ms_p50": round(statistics.median(lat), 2),
                                                "latency_ms_p95": round(sorted(lat)[int(len(lat) * .95) - 1], 2),
                                                "index_size": code.count()}
    stats = DATA / "index_stats.json"
    if stats.exists():
        results["index"] = json.loads(stats.read_text(encoding="utf-8"))
    out = EVAL / "results" / "retrieval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    for part in ("advisory", "code"):
        for kind, r in results[part].items():
            print(f"{part:9} {kind:7} n={r['n']:<4} " + "  ".join(f"R@{k}={r[f'recall@{k}']:.2f}" for k in KS)
                  + f"  MRR={r['mrr']:.2f}  p50={r['latency_ms_p50']}ms  p95={r['latency_ms_p95']}ms  size={r['index_size']}")
    return results
