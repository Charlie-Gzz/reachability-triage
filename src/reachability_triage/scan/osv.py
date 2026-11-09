"""Run osv-scanner against each target's frozen runtime lock and normalise the output.

One *finding* = one (target, package, version, vulnerability) tuple. osv-scanner
already groups aliases (GHSA-x / PYSEC-y / CVE-z describing the same bug) into
"groups", so each group becomes exactly one finding. That's the unit we label.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

from ..config import DATA, ROOT, WORK, Config, Target
from ..shell import run
from . import advisory_db
from .poetry_export import _roots, canon

RAW = DATA / "raw"
FINDINGS = DATA / "findings.jsonl"


def scanner_bin(cfg: Config) -> str:
    local = WORK / "bin" / ("osv-scanner.exe" if os.name == "nt" else "osv-scanner")
    exe = str(local) if local.exists() else shutil.which("osv-scanner")
    if not exe:
        raise SystemExit("osv-scanner not found; run `rt tools`")
    ver = run([exe, "--version"], capture=True).stdout
    if f"osv-scanner version: {cfg.osv_scanner_version}" not in ver:
        print(f"warning: expected osv-scanner {cfg.osv_scanner_version}, got:\n{ver}", file=sys.stderr)
    return exe


def scan_target(cfg: Config, t: Target, online: bool) -> Path:
    if not t.lockfile.exists():
        raise SystemExit(f"{t.lockfile} missing; run `rt setup {t.name}` first")
    cmd = [scanner_bin(cfg), "scan", "source", "--format", "json", "--no-resolve",
           "-L", f"requirements.txt:{t.lockfile.relative_to(ROOT).as_posix()}"]
    env = {}
    if not online:
        cmd.insert(3, "--offline")
        env = {"OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY": str(advisory_db.DB_DIR),
               "OSV_SCALIBR_LOCAL_DB_CACHE_DIRECTORY": str(advisory_db.DB_DIR)}
    proc = run(cmd, env=env, check=False, capture=True, cwd=ROOT)
    if proc.returncode not in (0, 1):          # 1 just means "vulnerabilities found"
        raise SystemExit(f"osv-scanner failed ({proc.returncode}):\n{proc.stderr[-2000:]}")
    # Strip the absolute checkout path so the committed file is machine-independent.
    text = proc.stdout.replace(str(ROOT) + os.sep, "").replace(str(ROOT).replace("\\", "/") + "/", "")
    out = RAW / f"{t.name}.osv.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return out


# ---------------------------------------------------------------- normalisation

def declared_deps(t: Target) -> set[str]:
    """Names of the project's *direct* dependencies, read from the checkout."""
    path = t.checkout / t.declared["path"]
    if t.declared["kind"] == "poetry":
        import tomllib
        return set(_roots(tomllib.loads(path.read_text(encoding="utf-8")), "main"))
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(canon(re.split(r"[\s\[<>=!~;]", line, maxsplit=1)[0]))
    return names


def _primary_id(ids: list[str]) -> str:
    for prefix in ("GHSA-", "PYSEC-", "CVE-"):
        for i in sorted(ids):
            if i.startswith(prefix):
                return i
    return sorted(ids)[0]


def _fixed_versions(records: list[dict], package: str) -> list[str]:
    fixed = set()
    for rec in records:
        for aff in rec.get("affected", []):
            if canon(aff.get("package", {}).get("name", "")) != package:
                continue
            for rng in aff.get("ranges", []):
                fixed.update(e["fixed"] for e in rng.get("events", []) if "fixed" in e)
    # Tie-break PEP 440-equal spellings ("2022.12.7" vs "2022.12.07") so the order never depends on set order.
    return sorted(fixed, key=lambda v: (_vkey(v), len(v), v))


def _vkey(v: str):
    try:
        return (0, Version(v))
    except InvalidVersion:
        return (1, v)


def _first_fix_above(fixed: list[str], installed: str) -> str | None:
    try:
        cur = Version(installed)
        return next((f for f in fixed if _vkey(f)[0] == 0 and Version(f) > cur), None)
    except InvalidVersion:
        return None


def normalise(t: Target, raw_path: Path) -> list[dict]:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    direct = declared_deps(t)
    findings = []
    for result in raw.get("results", []):
        for pkg in result.get("packages", []):
            name, version = canon(pkg["package"]["name"]), pkg["package"]["version"]
            by_id = {v["id"]: v for v in pkg.get("vulnerabilities", [])}
            for group in pkg.get("groups", []):
                ids = sorted(group["ids"])
                recs = [by_id[i] for i in ids if i in by_id]
                primary = _primary_id(ids)
                main = by_id.get(primary) or recs[0]
                aliases = sorted({a for r in recs for a in r.get("aliases", [])} | set(ids))
                cwes = sorted({c for r in recs for c in r.get("database_specific", {}).get("cwe_ids", [])})
                fixed = _fixed_versions(recs, name)
                findings.append({
                    "finding_id": f"{t.name}/{name}@{version}/{primary}",
                    "target": t.name,
                    "package": name,
                    "version": version,
                    "direct_dependency": name in direct,
                    "vuln_id": primary,
                    "aliases": aliases,
                    "cves": [a for a in aliases if a.startswith("CVE-")],
                    "cwes": cwes,
                    "summary": next((r.get("summary") for r in recs if r.get("summary")), "")
                               or (main.get("details", "").strip().splitlines() or [""])[0][:200],
                    "max_cvss": group.get("max_severity") or None,
                    "published": main.get("published"),
                    "fixed_versions": fixed,
                    "first_fixed_above_installed": _first_fix_above(fixed, version),
                })
    return sorted(findings, key=lambda f: f["finding_id"])


def write_findings(all_findings: list[dict]) -> None:
    FINDINGS.write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in all_findings), encoding="utf-8",
                        newline="\n")
    print(f"wrote {FINDINGS} ({len(all_findings)} findings)", file=sys.stderr)
