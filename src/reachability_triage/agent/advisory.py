"""Advisory records from the pinned offline DB, and deterministic vulnerable-symbol extraction.

Symbol extraction is rule-based (no LLM) so the static evidence node, the retrieval check and
the label drafter all see the same, explainable symbols.
"""
from __future__ import annotations

import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from ..config import WORK

ZIP_PATH = WORK / "osv-db" / "osv-scalibr" / "PyPI" / "all.zip"
CACHE = WORK / "advisories.json"

STOP = {
    "None", "True", "False", "GitHub", "JavaScript", "PyPI", "OpenSSL", "Python", "CPython", "PostgreSQL", "MySQL",
    "SQLite", "HTTPS", "HTTP", "TypeScript", "MacOS", "WebSocket", "WebSockets", "OAuth", "JSON", "YAML", "LaTeX",
    "ReDoS", "DoS", "XSS", "CSRF", "SSRF", "RCE", "README", "PoC", "NodeJS", "IPv", "IPython", "UTF", "NumPy",
    "PyYAML", "CPU", "GHSA", "CVE", "PYSEC", "Werkzeug", "Django", "Flask", "Jinja", "FastAPI", "SQLAlchemy",
    "MarkupSafe", "Pillow", "OpenID", "SameSite", "LibreOffice", "ImageMagick", "GraphQL", "ReportLab",
    "MongoDB", "MicroPython", "ReDOS", "CodeQL", "CxSCA", "AppSec", "CodeAnt", "MitM", "UltraJSON", "TianGong", "HackerOne", "BeautifulSoup", "LibTIFF", "FreeType", "WebP", "BlueSky", "YouTube",
    "PayPal", "OpenAI", "NVIDIA", "MacBook", "OpenBSD", "FreeBSD", "NetBSD", "UTF8", "OpenSSH", "VirusTotal",
}
STOP_SNAKE = {"pip_install", "proof_of", "end_of", "out_of", "file_name", "user_id"}


@lru_cache(maxsize=1)
def records() -> dict[str, dict]:
    """All PyPI records keyed by id, plus alias -> id entries. Cached as one JSON for speed."""
    if CACHE.exists() and (not ZIP_PATH.exists() or CACHE.stat().st_mtime >= ZIP_PATH.stat().st_mtime):
        return json.loads(CACHE.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    with zipfile.ZipFile(ZIP_PATH) as z:
        for n in z.namelist():
            rec = json.loads(z.read(n))
            out[rec["id"]] = rec
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


@lru_cache(maxsize=1)
def alias_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for rid, rec in records().items():
        for a in [rid, *rec.get("aliases", [])]:
            idx.setdefault(a, []).append(rid)
    return idx


def for_finding(f: dict) -> list[dict]:
    """Every record describing this finding (primary id + aliases), primary first."""
    ids: list[str] = []
    for a in [f["vuln_id"], *f.get("aliases", [])]:
        for rid in alias_index().get(a, []):
            if rid not in ids:
                ids.append(rid)
    recs = records()
    return [recs[i] for i in ids if i in recs]


def advisory_text(rec: dict) -> str:
    return f"{rec.get('summary', '')}\n\n{rec.get('details', '')}".strip()


def affected_ranges(recs: list[dict], package: str) -> list[str]:
    out = []
    for rec in recs:
        for aff in rec.get("affected", []):
            if re.sub(r"[-_.]+", "-", aff.get("package", {}).get("name", "")).lower() != package:
                continue
            for rng in aff.get("ranges", []):
                ev = rng.get("events", [])
                intro = next((e["introduced"] for e in ev if "introduced" in e), "0")
                fix = next((e.get("fixed") or e.get("last_affected") for e in ev if "fixed" in e or "last_affected" in e), None)
                out.append(f">={intro}, <{fix}" if fix else f">={intro}")
    return sorted(set(out))


_BACKTICK = re.compile(r"`([A-Za-z_][\w.]*)(?:\([^`]*\))?`")
_DOTTED = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*(\(\))?")
_CALLISH = re.compile(r"\b([A-Za-z_]\w{2,})\(\)")
_CAMEL = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b")
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b")
_URLISH = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|org|io|net|dev|html|md|txt|py|json|yaml|yml)\b")


def extract_symbols(text: str, import_names: list[str], package: str, max_n: int = 8) -> list[str]:
    """Rank candidate vulnerable symbols named in advisory text.

    Strong signals first: backticked identifiers, dotted names rooted in the package's import
    names, `name()` call forms; then CamelCase class names and snake_case function names.
    """
    text = _URLISH.sub(" ", text or "")
    roots = {n.lower() for n in import_names} | {package.replace("-", "_")}
    scored: dict[str, float] = {}

    def add(sym: str, score: float):
        sym = sym.strip(".")
        if not sym or len(sym) < 3 or sym in STOP or sym.lower() in roots or sym.lower() == package:
            return
        if sym.split(".")[0] in ("e", "i", "eg", "etc", "v", "www", "http", "https", "self") or re.match(r"^v?\d", sym):
            return
        if re.fullmatch(r"[A-Z][A-Z0-9_]+", sym):      # acronyms and ALL_CAPS markers (CVE, HTML, EVOHUNT_X)
            return
        scored[sym] = max(scored.get(sym, 0), score)

    for m in _BACKTICK.finditer(text):
        add(m.group(1), 3.0)
    for m in _DOTTED.finditer(text):
        name = m.group(1)
        head = name.split(".")[0].lower()
        if head in roots:
            add(name, 3.5)
        elif m.group(2) or any(c.isupper() for c in name.split(".")[0][:1]):
            add(name, 1.5)
    for m in _CALLISH.finditer(text):
        add(m.group(1), 2.5)
    for m in _CAMEL.finditer(text):
        add(m.group(1), 1.2)
    for m in _SNAKE.finditer(text):
        if m.group(1) not in STOP_SNAKE:
            add(m.group(1), 1.0)
    # drop symbols subsumed by a stronger dotted one (keep "yaml.full_load", drop bare "full_load" only if weaker)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], text.find(kv[0])))
    return [s for s, _ in ranked[:max_n]]


def symbols_for(f: dict, recs: list[dict], import_names: list[str], summary_only: bool = False) -> list[str]:
    """Symbols for a finding. summary_only=True mimics having only the scanner's one-line summary."""
    if summary_only:
        text = f.get("summary", "")
    else:
        text = "\n".join(advisory_text(r) for r in recs) or f.get("summary", "")
    syms = extract_symbols(text, import_names, f["package"])
    for rec in recs:          # structured hints, when an advisory has them
        for aff in rec.get("affected", []):
            es = aff.get("ecosystem_specific") or {}
            for imp in es.get("imports", []) or []:
                for s in imp.get("symbols", []) or []:
                    full = f"{imp.get('path', '')}.{s}".strip(".")
                    if full not in syms:
                        syms.insert(0, full)
            for fn in es.get("affected_functions", []) or []:
                if fn not in syms:
                    syms.insert(0, fn)
    return syms[:10]


def import_names_for(package: str, target: str | None) -> list[str]:
    """Import names for a distribution, from the target image's metadata, else a heuristic."""
    from ..config import DATA
    if target:
        path = DATA / "import_names" / f"{target}.json"
        if path.exists():
            m = json.loads(path.read_text(encoding="utf-8"))
            if m.get(package):
                return m[package]
    known = {"pyyaml": ["yaml"], "pillow": ["PIL"], "python-jose": ["jose"], "pyjwt": ["jwt"], "beautifulsoup4": ["bs4"],
             "gitpython": ["git"], "python-multipart": ["multipart"], "scikit-learn": ["sklearn"], "pycryptodome": ["Crypto"],
             "python-dateutil": ["dateutil"], "msgpack-python": ["msgpack"], "markdown": ["markdown"], "pymysql": ["pymysql"],
             "flask-cors": ["flask_cors"], "python-ldap": ["ldap"], "setuptools": ["setuptools", "pkg_resources"],
             "protobuf": ["google.protobuf"], "dnspython": ["dns"], "pycrypto": ["Crypto"], "ecdsa": ["ecdsa"]}
    return known.get(package, [package.replace("-", "_").lower()])


def path_exists() -> bool:
    return Path(ZIP_PATH).exists()
