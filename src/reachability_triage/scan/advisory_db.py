"""Build a pinned, offline OSV database for PyPI that osv-scanner can read.

osv-scanner's --offline mode reads <cache>/osv-scalibr/<Ecosystem>/all.zip, a zip of
OSV JSON records (normally downloaded from osv.dev). We build that zip ourselves
from two public advisory repos at pinned commits, so a rescan months from now
produces the same findings. This covers the two sources osv.dev itself uses for
PyPI: GitHub Security Advisories (GHSA-*) and the PyPA database (PYSEC-*).
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import yaml

from ..config import WORK
from ..shell import run

DB_DIR = WORK / "osv-db"
ZIP_PATH = DB_DIR / "osv-scalibr" / "PyPI" / "all.zip"


def _fetch(name: str, src: dict) -> Path:
    """Sparse, blobless, single-commit fetch of just the advisory directory."""
    d = WORK / "advisory-src" / name
    if not (d / ".git").exists():
        d.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=d)
        run(["git", "config", "core.autocrlf", "false"], cwd=d)
        run(["git", "remote", "add", "origin", src["url"]], cwd=d)
        run(["git", "sparse-checkout", "set", src["path"]], cwd=d)
        run(["git", "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", src["commit"]], cwd=d)
        run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=d)
    return d / src["path"]


def _is_pypi(rec: dict) -> bool:
    return any(a.get("package", {}).get("ecosystem") == "PyPI" for a in rec.get("affected", []))


def build(sources: dict) -> Path:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in sources.items():
            root = _fetch(name, src)
            n = 0
            for f in sorted(root.rglob(f"*.{src['format']}")):
                text = f.read_text(encoding="utf-8")
                rec = json.loads(text) if src["format"] == "json" else yaml.safe_load(text)
                if rec.get("withdrawn") or not _is_pypi(rec):
                    continue
                z.writestr(f"{rec['id']}.json", json.dumps(rec, default=str))
                n += 1
            counts[name] = n
    print(f"wrote {ZIP_PATH}: {counts}", file=sys.stderr)
    return ZIP_PATH


def records() -> dict[str, dict]:
    """All records in the built DB, keyed by id. Used to enrich findings."""
    with zipfile.ZipFile(ZIP_PATH) as z:
        return {Path(n).stem: json.loads(z.read(n)) for n in z.namelist()}
