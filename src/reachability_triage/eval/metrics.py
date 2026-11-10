"""`rt eval`: every number from the committed run records. No LLM calls.

Positive class = reachable. Ground-truth `uncertain` labels are excluded from graded metrics.
- precision        TP / predicted reachable
- recall           TP / truly reachable              (an `uncertain` prediction is not a catch)
- false-suppression truly reachable predicted not_reachable / truly reachable   (the dangerous error)
- noise reduction  correctly suppressed (truly not reachable, predicted not_reachable) / all graded findings
- uncertain rate   predicted uncertain / all graded findings
95% CIs: percentile bootstrap over findings (2,000 resamples, fixed seed).
"""
from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from datetime import UTC, datetime

from ..bench import bench_cases
from ..config import EVAL, RUNS

CONFIGS = ["full", "no-retrieval", "no-reflection", "local"]
DATASETS = ["bench-test", "real-eval"]
B = 2000
SEED = 7


def ground_truth() -> dict[str, dict]:
    from ..bench import bench_findings
    from .draft_labels import load_labels
    gt = {}
    cases = {c["case"]: c for c in bench_cases()}
    for f in bench_findings():
        c = cases[f["target"].split("/", 1)[1]]
        gt[f["finding_id"]] = {"label": c["label"], "status": "final", "dataset": "bench", "split": c["split"],
                               "category": c["category"]}
    for fid, d in load_labels().items():
        gt[fid] = {"label": d["label"], "status": d["status"], "dataset": "real"}
    return gt


def _records(config: str) -> list[dict]:
    d = RUNS / config
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def _core(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (truth, predicted) over graded findings."""
    n = len(pairs)
    tp = sum(1 for t, p in pairs if t == "reachable" and p == "reachable")
    pred_r = sum(1 for _, p in pairs if p == "reachable")
    true_r = sum(1 for t, _ in pairs if t == "reachable")
    fs = sum(1 for t, p in pairs if t == "reachable" and p == "not_reachable")
    safe = sum(1 for t, p in pairs if t == "not_reachable" and p == "not_reachable")
    unc = sum(1 for _, p in pairs if p == "uncertain")
    return {"n": n, "true_reachable": true_r, "tp": tp, "predicted_reachable": pred_r, "false_suppressions": fs,
            "precision": tp / pred_r if pred_r else None, "recall": tp / true_r if true_r else None,
            "false_suppression_rate": fs / true_r if true_r else None,
            "noise_reduction": safe / n if n else None, "uncertain_rate": unc / n if n else None,
            "suppressed_rate": sum(1 for _, p in pairs if p == "not_reachable") / n if n else None,
            "accuracy": sum(1 for t, p in pairs if t == p) / n if n else None}


def _ci(pairs, key) -> list[float] | None:
    if not pairs:
        return None
    rng = random.Random(SEED)
    vals = []
    for _ in range(B):
        v = _core([pairs[rng.randrange(len(pairs))] for _ in pairs])[key]
        if v is not None:
            vals.append(v)
    if len(vals) < B * 0.5:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


def evaluate(records: list[dict], gt: dict, dataset: str) -> dict | None:
    rows = []
    for r in records:
        g = gt.get(r["finding_id"])
        if not g:
            continue
        if dataset == "bench-test" and not (g["dataset"] == "bench" and g["split"] == "test"):
            continue
        if dataset == "real-eval" and g["dataset"] != "real":
            continue
        rows.append((r, g))
    if not rows:
        return None
    graded = [(g["label"], r["final"]["verdict"]) for r, g in rows if g["label"] != "uncertain"]
    m = _core(graded)
    for k in ("precision", "recall", "false_suppression_rate", "noise_reduction", "uncertain_rate"):
        m[f"{k}_ci95"] = _ci(graded, k)
        if m[k] is not None:
            m[k] = round(m[k], 3)
    for k in ("accuracy", "suppressed_rate"):
        if m[k] is not None:
            m[k] = round(m[k], 3)
    tot = [r["totals"] for r, _ in rows]
    m.update({
        "findings_run": len(rows), "excluded_truth_uncertain": len(rows) - len(graded),
        "labels_reviewed": sum(1 for _, g in rows if g["status"] in ("final", "reviewed")),
        "provisional": any(g["status"] == "pending_review" for _, g in rows),
        "predictions": dict(Counter(r["final"]["verdict"] for r, _ in rows)),
        "llm_calls_per_finding": round(statistics.mean(t["llm_calls"] for t in tot), 2),
        "tokens_in_per_finding": round(statistics.mean(t["tokens_in"] for t in tot)),
        "tokens_out_per_finding": round(statistics.mean(t["tokens_out"] for t in tot)),
        "cost_usd_est_per_finding": round(statistics.mean(t["cost_usd_est"] for t in tot), 4),
        "seconds_per_finding_p50": round(statistics.median(t["seconds"] for t in tot), 1),
        "seconds_per_finding_mean": round(statistics.mean(t["seconds"] for t in tot), 1),
        "parse_errors": sum(1 for r, _ in rows if "parse_error" in (r.get("errors") or [])),
        "changed_by_reflection": sum(1 for r, _ in rows if r["final"].get("changed_by_reflection")),
    })
    if dataset == "bench-test":
        by_cat = {}
        for r, g in rows:
            c = by_cat.setdefault(g["category"], {"n": 0, "correct": 0})
            c["n"] += 1
            c["correct"] += int(r["final"]["verdict"] == g["label"])
        m["by_category"] = by_cat
    m["errors"] = [{"finding_id": r["finding_id"], "truth": g["label"], "predicted": r["final"]["verdict"]}
                   for r, g in rows if g["label"] != "uncertain" and r["final"]["verdict"] != g["label"]]
    return m


def remediation_summary(config: str = "full") -> dict | None:
    recs = _records(f"{config}-remediation")
    if not recs:
        return None
    red = sum(1 for r in recs if r["reason"] != "no_failing_test")
    return {"attempted": len(recs), "failing_test_written": red,
            "fixed": sum(1 for r in recs if r["status"] == "fixed"),
            "fixed_by": dict(Counter(r.get("fix_kind") for r in recs if r["status"] == "fixed")),
            "failure_reasons": dict(Counter(r["reason"] for r in recs if r["status"] != "fixed")),
            "llm_calls": sum(r.get("llm_calls", 0) for r in recs),
            "fixed_ids": [r["finding_id"] for r in recs if r["status"] == "fixed"]}


def resolved_model(rec: dict) -> str | None:
    """The model that actually answered (e.g. claude-sonnet-...), not the config alias ("sonnet")."""
    return next((a["model"] for s in rec["steps"] for a in s.get("attempts") or [] if a.get("model")), None)


def _pct(v):
    return "n/a" if v is None else f"{100 * v:.0f}%"


def _ci_s(ci):
    return "" if not ci else f" [{100 * ci[0]:.0f}–{100 * ci[1]:.0f}]"


def run_eval(quiet: bool = False) -> dict:
    from ..agent.providers import claude_calls_used
    gt = ground_truth()
    results = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "configs": {}}
    for c in CONFIGS:
        recs = _records(c)
        if not recs:
            continue
        results["configs"][c] = {d: m for d in DATASETS if (m := evaluate(recs, gt, d))}
        results["configs"][c]["provider"] = recs[0]["provider"]
        results["configs"][c]["model"] = next(filter(None, map(resolved_model, recs)), None) or recs[0]["model"]
    results["remediation"] = remediation_summary()
    rp = EVAL / "results" / "retrieval.json"
    results["retrieval"] = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None
    real_labels = [g for g in gt.values() if g["dataset"] == "real"]
    results["labels"] = {"real_total": len(real_labels),
                         "real_reviewed": sum(1 for g in real_labels if g["status"] == "reviewed"),
                         "real_pending": sum(1 for g in real_labels if g["status"] == "pending_review"),
                         "real_label_counts": dict(Counter(g["label"] for g in real_labels))}
    results["claude_calls_total"] = claude_calls_used()
    full = results["configs"].get("full", {})
    fr, fb = full.get("real-eval"), full.get("bench-test")
    fixed = (results["remediation"] or {}).get("fixed", 0)
    # Only headline the real set once it has fully run and has enough graded findings; else the benchmark.
    use_real = bool(fr and fr["findings_run"] >= 45 and fr["n"] >= 10 and fr["false_suppression_rate"] is not None)
    src = fr if use_real else fb
    if src:
        tag = (" (real set, provisional labels)" if fr["provisional"] else " (real set)") if use_real else " (benchmark test split)"
        results["headline"] = (f"Suppresses {_pct(src['noise_reduction'])} of scanner noise with a "
                               f"{_pct(src['false_suppression_rate'])} false-suppression rate{tag}, and fixed "
                               f"{fixed} real vulnerabilit{'y' if fixed == 1 else 'ies'} test-first.")
    out = EVAL / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "results.md").write_text(_markdown(results), encoding="utf-8", newline="\n")
    if not quiet:
        print(_markdown(results))
    return results


def _markdown(res: dict) -> str:
    L = ["# Results", "", f"_Generated {res['generated']} by `rt eval` from `runs/` (no LLM calls)._", ""]
    if res.get("headline"):
        L += [f"**{res['headline']}**", ""]
    lab = res["labels"]
    if lab["real_pending"]:
        L += [f"> Real-set numbers are **provisional**: {lab['real_pending']} of {lab['real_total']} real labels are "
              "machine-drafted and still pending human review (`rt review`). Ground-truth `uncertain` labels are "
              "excluded from graded metrics.", ""]
    L += ["Brackets are 95% bootstrap confidence intervals. With samples this small, differences inside the "
          "intervals are noise.", ""]
    for d in DATASETS:
        title = "Synthetic benchmark (test split, final labels)" if d == "bench-test" else "Real-repo eval set (50 findings)"
        L += [f"## {title}", "", "| Config | Model | n graded | False-suppression | Precision | Recall | Noise reduction | "
              "Uncertain | Calls/finding | Tokens in/out | Est. $/finding | p50 s |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for c, by in res["configs"].items():
            m = by.get(d)
            if not m:
                continue
            L.append(f"| `{c}` | {by['model']} | {m['n']} | {_pct(m['false_suppression_rate'])}{_ci_s(m['false_suppression_rate_ci95'])} | "
                     f"{_pct(m['precision'])}{_ci_s(m['precision_ci95'])} | {_pct(m['recall'])}{_ci_s(m['recall_ci95'])} | "
                     f"{_pct(m['noise_reduction'])}{_ci_s(m['noise_reduction_ci95'])} | {_pct(m['uncertain_rate'])} | "
                     f"{m['llm_calls_per_finding']} | {m['tokens_in_per_finding']}/{m['tokens_out_per_finding']} | "
                     f"{m['cost_usd_est_per_finding']} | {m['seconds_per_finding_p50']} |")
        L.append("")
    rem = res.get("remediation")
    if rem:
        L += ["## Test-first remediation", "",
              f"{rem['attempted']} reachable findings attempted → {rem['failing_test_written']} with a failing (red) test → "
              f"**{rem['fixed']} fixed green with the suite intact** ({rem['fixed_by']}). Failure reasons: {rem['failure_reasons']}.", ""]
    r = res.get("retrieval")
    if r:
        L += ["## Retrieval (Chroma vs FAISS, same embeddings)", "", "| Index | Store | n | R@1 | R@5 | MRR | p50 ms |", "|---|---|---|---|---|---|---|"]
        for part in ("advisory", "code"):
            for kind, m in r[part].items():
                L.append(f"| {part} | {kind} | {m['n']} | {m['recall@1']:.2f} | {m['recall@5']:.2f} | {m['mrr']:.2f} | {m['latency_ms_p50']} |")
        L.append("")
    L += [f"Claude calls used in total (all runs, incl. development): {res['claude_calls_total']} of the 1,500 cap.",
          "Cost is an API-list-price **estimate**; runs used a Claude subscription via `claude -p`.", ""]
    return "\n".join(L)
