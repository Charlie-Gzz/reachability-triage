"""Build a pinned, offline OSV database for PyPI that osv-scanner can read.

osv-scanner's --offline mode reads <cache>/osv-scalibr/<Ecosystem>/all.zip, a zip of
OSV JSON records (normally downloaded from osv.dev). We build that zip ourselves
from two public advisory repos at pinned commits, so a rescan months from now
produces the same findings. This covers the two sources osv.dev itself uses for
PyPI: GitHub Security Advisories (GHSA-*) and the PyPA database (PYSEC-*).
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from ..config import WORK
from ..shell import run

DB_DIR = WORK / "osv-db"
ZIP_PATH = DB_DIR / "osv-scalibr" / "PyPI" / "all.zip"


def _fetch(name: str, src: dict) -> Path:
    """Single-commit shallow fetch of an advisory repo (nothing checked out)."""
    d = WORK / "advisory-src" / name
    if not (d / ".git").exists() or not (d / ".git" / "HEAD").exists():
        d.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=d)
        run(["git", "config", "core.autocrlf", "false"], cwd=d)
        run(["git", "remote", "add", "origin", src["url"]], cwd=d)
        # Fetch the commit with all blobs but check nothing out: files are read from the object store.
        run(["git", "fetch", "-q", "--depth", "1", "origin", src["commit"]], cwd=d)
        run(["git", "update-ref", "HEAD", "FETCH_HEAD"], cwd=d)
    return d / src["path"]


def _blobs(repo: Path, path: str, ext: str):
    """Yield (name, text) for every file under `path` at HEAD, read from git's object store.

    Reading the checked-out files doesn't work reliably on Windows: Defender blocks some advisory
    files (exploit strings in PoCs), so we never touch the working tree.
    """
    listing = subprocess.run(["git", "ls-tree", "-r", "HEAD", "--", path], cwd=repo, capture_output=True,
                             check=True).stdout.decode()
    entries = [(l.split()[2], l.split("\t", 1)[1]) for l in listing.splitlines() if l.endswith("." + ext)]
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha, name in sorted(entries, key=lambda e: e[1]):
            proc.stdin.write(sha.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)
            yield name, data.decode("utf-8", "replace")
    finally:
        proc.stdin.close()
        proc.wait()


def _is_pypi(rec: dict) -> bool:
    return any(a.get("package", {}).get("ecosystem") == "PyPI" for a in rec.get("affected", []))


def build(sources: dict) -> Path:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for name, src in sources.items():
            _fetch(name, src)
            n = 0
            for _, text in _blobs(WORK / "advisory-src" / name, src["path"], src["format"]):
                if "PyPI" not in text:          # cheap pre-filter; most GHSA records are other ecosystems
                    continue
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
