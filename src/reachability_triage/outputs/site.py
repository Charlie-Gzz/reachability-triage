"""`rt site`: build the static case explorer data from committed runs + results.

Data is emitted as small .js files (window.SIEVE = ...) instead of JSON so the site also works when
opened straight from disk (file://), not only from GitHub Pages or a local server.
"""
from __future__ import annotations

import json
import re
import shutil
import sys

from ..config import ASSETS, EVAL, RUNS, SITE
from ..eval.metrics import resolved_model

CONFIGS = ["full", "no-retrieval", "no-reflection", "local"]


def slug(config: str, fid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{config}__{fid}")


def _js(path, var: str, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"window.{var} = {json.dumps(obj, separators=(',', ':'), default=str)};\n", encoding="utf-8",
                    newline="\n")


def _trim(rec: dict) -> dict:
    """Keep what the timeline shows; cap long texts so the site stays small."""
    rec = json.loads(json.dumps(rec, default=str))
    for st in rec["steps"]:
        out = st.get("output")
        if isinstance(out, dict):
            for c in out.get("chunks", []) or []:
                c["text"] = c["text"][:1600]
            for s in out.get("vulnerable_call_sites", []) or []:
                s.pop("snippet", None) if not s.get("path") else None
        for a in st.get("attempts", []) or []:
            if "raw" in a:
                a["raw"] = a["raw"][:2500]
    rec["finding"].pop("published", None)
    rec["model"] = resolved_model(rec) or rec.get("model")
    return rec


def _upstream(cfg_targets, target: str) -> str | None:
    for t in cfg_targets:
        if t.name == target:
            return f"{t.url}/blob/{t.commit}"
    return None


def featured(rows: list[dict], rem: dict) -> list[dict]:
    """A clear catch, a correct suppression, a full red-to-green fix, and one honest failure."""
    out = []
    full = [r for r in rows if r["config"] == "full"]

    def pick(pred, why, key=lambda r: 0):
        cands = sorted([r for r in full if pred(r) and r["slug"] not in {o["slug"] for o in out}], key=key)
        if cands:
            out.append({"slug": cands[0]["slug"], "why": why, "finding_id": cands[0]["finding_id"]})

    pick(lambda r: r["dataset"] == "bench" and r["truth"] == "reachable" and r["correct"] and r["path_len"] >= 3,
         "Clear catch: the vulnerable call sits three hops from a route, behind a wrapper", key=lambda r: -r["path_len"])
    pick(lambda r: r["dataset"] == "bench" and r["truth"] == "reachable" and r["correct"],
         "Clear catch: user input reaches the vulnerable function")
    pick(lambda r: r["dataset"] == "bench" and r["truth"] == "not_reachable" and r["correct"]
         and r["category"] in ("config_disabled", "dead_code", "test_only"),
         "Correct suppression: the package is used, but not the vulnerable part")
    fixed = [fid for fid, v in rem.items() if v["status"] == "fixed"]
    if fixed:
        r = next((r for r in full if r["finding_id"] == fixed[0]), None)
        if r:
            out.append({"slug": r["slug"], "why": "Full fix: failing test → upgrade → green, suite intact",
                        "finding_id": r["finding_id"]})
    pick(lambda r: r["truth"] in ("reachable", "not_reachable") and r["truth_status"] == "final" and not r["correct"],
         "Honest failure: where the agent got it wrong", key=lambda r: (r["truth"] != "reachable", r["finding_id"]))
    return out[:5]


def build_site() -> None:
    from ..config import load
    from ..eval.metrics import ground_truth
    cfg = load()
    gt = ground_truth()
    res_p = EVAL / "results" / "results.json"
    results = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else {}
    data = SITE / "data"
    if data.exists():
        shutil.rmtree(data)
    rem = {}
    rem_dir = RUNS / "full-remediation"
    if rem_dir.exists():
        for p in rem_dir.glob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            rem[r["finding_id"]] = r
    rows = []
    for c in CONFIGS:
        d = RUNS / c
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            fid = rec["finding_id"]
            g = gt.get(fid, {})
            s = slug(c, fid)
            sites = rec["steps"][2]["output"]["vulnerable_call_sites"] if len(rec["steps"]) > 2 else []
            path_len = max((len(x.get("path") or []) for x in sites), default=0)
            row = {"slug": s, "config": c, "finding_id": fid, "dataset": rec["dataset"], "split": rec.get("split"),
                   "target": rec["target"], "package": rec["finding"]["package"], "version": rec["finding"]["version"],
                   "vuln_id": rec["finding"]["vuln_id"], "summary": rec["finding"].get("summary", "")[:160],
                   "cvss": rec["finding"].get("max_cvss"), "verdict": rec["final"]["verdict"],
                   "confidence": rec["final"]["confidence"], "truth": g.get("label"), "truth_status": g.get("status"),
                   "category": g.get("category"),
                   "correct": (g.get("label") == rec["final"]["verdict"]) if g.get("label") not in (None, "uncertain") else None,
                   "tokens": rec["totals"]["tokens_in"] + rec["totals"]["tokens_out"], "seconds": rec["totals"]["seconds"],
                   "path_len": path_len, "in_eval": (rec["dataset"] == "bench" and rec.get("split") == "test")
                   or (rec["dataset"] == "real" and g.get("label") is not None),
                   "remediation": rem[fid]["status"] if c == "full" and fid in rem else None}
            rows.append(row)
            case = _trim(rec)
            case["truth"] = g
            case["upstream"] = _upstream(cfg.targets, rec["target"])
            if c == "full" and fid in rem:
                case["remediation"] = rem[fid]
            _js(data / "cases" / f"{s}.js", "SIEVE_CASE", case)
    feat = featured(rows, rem)
    _js(data / "index.js", "SIEVE", {"rows": rows, "results": results, "featured": feat,
                                      "generated": results.get("generated")})
    # charts + diagrams for the overview page
    dst = SITE / "assets"
    if dst.exists():
        shutil.rmtree(dst)
    for sub in ("charts", "diagram"):
        if (ASSETS / sub).exists():
            shutil.copytree(ASSETS / sub, dst / sub)
    print(f"site: {len(rows)} case pages, {len(feat)} featured -> {SITE / 'index.html'}", file=sys.stderr)
