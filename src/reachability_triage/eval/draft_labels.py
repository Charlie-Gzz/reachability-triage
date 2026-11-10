"""Draft real-set labels with a deterministic script: no LLM, and independent of the agent's code paths.

Deliberately NOT the agent's AST analyser or symbol extractor: a plain text search over the target's
first-party source, with its own, simpler symbol rule (backticked names and package-rooted dotted
names in the advisory). Sharing code with the agent would let the agent's bugs grade themselves.

Every draft is stored as status=pending_review with its evidence and the rule that fired; Charlie
confirms or changes each one on the review page (`rt review`).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from ..config import DATA, Config

LABELS = DATA / "labels.jsonl"
SKIP = {".git", "node_modules", "migrations", "__pycache__", "frontend", "docs"}


def _advisories(f: dict) -> list[dict]:
    import zipfile

    from ..scan.advisory_db import ZIP_PATH
    want = {f["vuln_id"], *f.get("aliases", [])}
    out = []
    with zipfile.ZipFile(ZIP_PATH) as z:
        for name in z.namelist():
            if Path(name).stem in want:
                out.append(json.loads(z.read(name)))
    return out


def _names(text: str, import_names: list[str]) -> list[str]:
    found = []
    for m in re.finditer(r"`([A-Za-z_][\w.]*)`", text):
        found.append(m.group(1))
    roots = "|".join(re.escape(n) for n in import_names)
    if roots:
        for m in re.finditer(rf"\b(?:{roots})(?:\.[A-Za-z_]\w*)+", text):
            found.append(m.group(0))
    out = []
    for n in found:
        leaf = n.split(".")[-1]
        if len(leaf) >= 4 and leaf not in out and not leaf.isupper():
            out.append(leaf)
    return out[:8]


def _source_files(root: Path, app_dirs: list[str]) -> list[Path]:
    files = []
    for d in app_dirs:
        for p in (root / d).rglob("*"):
            if p.suffix in (".py", ".html") and not SKIP.intersection(p.relative_to(root).parts):
                files.append(p)
    return files


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts or "test" in parts or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def draft_one(cfg: Config, f: dict, import_map: dict) -> dict:
    t = cfg.target(f["target"])
    imports = import_map.get(f["package"]) or [f["package"].replace("-", "_")]
    recs = _advisories(f)
    text = "\n".join(f"{r.get('summary', '')}\n{r.get('details', '')}" for r in recs)
    symbols = _names(text, imports)
    imp_re = re.compile(rf"^\s*(?:from|import)\s+(?:{'|'.join(re.escape(i) for i in imports)})\b", re.M)
    imp_hits, sym_hits = [], []
    for p in _source_files(t.checkout, t.app_dirs + t.template_dirs):
        rel = p.relative_to(t.checkout).as_posix()
        if _is_test(rel):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if p.suffix == ".py" and imp_re.match(line):
                imp_hits.append(f"{rel}:{i}")
            for s in symbols:
                if re.search(rf"\b{re.escape(s)}\b", line):
                    sym_hits.append({"location": f"{rel}:{i}", "symbol": s, "line": line.strip()[:160]})
    if not imp_hits and not f["direct_dependency"]:
        label, rule = "uncertain", "transitive dependency, never imported by app code: used only through other packages"
    elif not imp_hits:
        label, rule = "not_reachable", "declared but never imported by first-party (non-test) code"
    elif not symbols:
        label, rule = "uncertain", "imported; advisory names no specific function to search for"
    elif sym_hits:
        label, rule = "reachable", "imported, and a symbol named in the advisory appears in first-party code"
    else:
        label, rule = "not_reachable", "imported, but none of the symbols named in the advisory appear in first-party code"
    return {"finding_id": f["finding_id"], "status": "pending_review", "label": label, "drafted_label": label,
            "draft_rule": rule, "draft_symbols": symbols,
            "draft_evidence": {"imports": imp_hits[:10], "symbol_hits": sym_hits[:10],
                               "import_count": len(imp_hits), "symbol_hit_count": len(sym_hits)},
            "notes": "", "drafted_at": datetime.now(UTC).isoformat(timespec="seconds"), "reviewed_at": None}


def load_labels() -> dict[str, dict]:
    if not LABELS.exists():
        return {}
    return {d["finding_id"]: d for d in (json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines() if l)}


def save_labels(labels: dict[str, dict]) -> None:
    LABELS.write_text("".join(json.dumps(labels[k], sort_keys=True) + "\n" for k in sorted(labels)),
                      encoding="utf-8", newline="\n")


def draft_all(cfg: Config) -> None:
    from collections import Counter

    from ..agent.runner import eval_real_ids, real_findings
    ids = set(eval_real_ids())
    if not ids:
        raise SystemExit("no eval set; run `rt sample` first")
    existing = load_labels()
    maps = {}
    for p in (DATA / "import_names").glob("*.json"):
        maps[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    for f in real_findings():
        if f["finding_id"] not in ids:
            continue
        if existing.get(f["finding_id"], {}).get("status") == "reviewed":
            continue                       # never overwrite Charlie's review
        existing[f["finding_id"]] = draft_one(cfg, f, maps.get(f["target"], {}))
    save_labels(existing)
    c = Counter((d["status"], d["label"]) for d in existing.values())
    print(f"{len(existing)} labels: " + ", ".join(f"{s}/{l}={n}" for (s, l), n in sorted(c.items())))
