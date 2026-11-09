"""Synthetic benchmark: small apps under bench/cases/<case>, ground truth in bench/labels.jsonl.

Each case is one finding: (case app, package, pinned version, advisory). Findings are built from the
pinned advisory DB in the same shape as the real-repo findings, and every pinned version is checked
with osv-scanner so the benchmark only uses versions the scanner really flags.
"""
from __future__ import annotations

import json
import subprocess
import sys

from .agent import advisory
from .config import BENCH, ROOT, WORK, load
from .scan.osv import _first_fix_above, _fixed_versions, _primary_id

LABELS = BENCH / "labels.jsonl"
FINDINGS = BENCH / "findings.jsonl"


def bench_cases() -> list[dict]:
    if not LABELS.exists():
        return []
    return [json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines() if l.strip()]


def bench_findings() -> list[dict]:
    if not FINDINGS.exists():
        return []
    return [json.loads(l) for l in FINDINGS.read_text(encoding="utf-8").splitlines() if l.strip()]


def _scanner_ids(case: str) -> set[str]:
    from .scan.osv import scanner_bin
    exe = scanner_bin(load())
    req = BENCH / "cases" / case / "requirements.txt"
    env = {"OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY": str(WORK / "osv-db"),
           "OSV_SCALIBR_LOCAL_DB_CACHE_DIRECTORY": str(WORK / "osv-db")}
    import os
    proc = subprocess.run([exe, "scan", "source", "--offline", "--format", "json", "--no-resolve", "-L",
                           f"requirements.txt:{req.relative_to(ROOT).as_posix()}"], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", env={**os.environ, **env})
    ids = set()
    for res in json.loads(proc.stdout or "{}").get("results", []):
        for pkg in res.get("packages", []):
            for v in pkg.get("vulnerabilities", []):
                ids.add(v["id"])
                ids.update(v.get("aliases", []))
    return ids


def build_findings() -> list[dict]:
    out = []
    for c in bench_cases():
        f0 = {"vuln_id": c["vuln_id"], "aliases": []}
        recs = advisory.for_finding(f0)
        if not recs:
            raise SystemExit(f"{c['case']}: {c['vuln_id']} not in the pinned DB")
        ids = sorted({r["id"] for r in recs} | {a for r in recs for a in r.get("aliases", [])})
        flagged = _scanner_ids(c["case"])
        if not flagged & set(ids):
            raise SystemExit(f"{c['case']}: osv-scanner does not flag {c['package']}=={c['version']} for {c['vuln_id']}")
        primary = _primary_id(ids)
        main = next((r for r in recs if r["id"] == primary), recs[0])
        fixed = _fixed_versions(recs, c["package"])
        sev = next((s.get("score") for r in recs for s in r.get("severity", []) if s.get("type") == "CVSS_V3"), None)
        out.append({
            "finding_id": f"bench/{c['case']}/{c['package']}@{c['version']}/{primary}",
            "target": f"bench/{c['case']}", "package": c["package"], "version": c["version"],
            "direct_dependency": True, "vuln_id": primary, "aliases": ids,
            "cves": [a for a in ids if a.startswith("CVE-")],
            "cwes": sorted({w for r in recs for w in r.get("database_specific", {}).get("cwe_ids", [])}),
            "summary": main.get("summary") or main.get("details", "")[:200],
            "max_cvss": sev, "published": main.get("published"), "fixed_versions": fixed,
            "first_fixed_above_installed": _first_fix_above(fixed, c["version"]),
            "split": c["split"],
        })
        print(f"ok  {c['case']:20} {c['package']}=={c['version']} {primary}  ({c['split']})", file=sys.stderr)
    FINDINGS.write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in out), encoding="utf-8", newline="\n")
    print(f"wrote {FINDINGS} ({len(out)} findings)", file=sys.stderr)
    return out
