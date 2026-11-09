"""Advisory index (from the pinned DB) and code indexes (function-level chunks), in Chroma and FAISS.

Embeddings are computed once and written to both stores, so the store benchmark compares the
stores, not the embeddings.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..agent import advisory
from ..agent.static import iter_py
from ..config import BENCH, DATA, LOCKS, Config
from .store import INDEX_DIR, Hit, embedder, open_store

ADVISORY_COLLECTION = "advisories"
CODE_COLLECTION = "code"
MAX_CHUNK_LINES = 60


# ------------------------------------------------------------------ advisory chunks

def _locked_packages() -> set[str]:
    pkgs = set()
    for f in LOCKS.glob("*.txt"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "==" in line and not line.startswith("#"):
                pkgs.add(re.sub(r"[-_.]+", "-", line.split("==")[0].strip()).lower())
    if (BENCH / "findings.jsonl").exists():
        for line in (BENCH / "findings.jsonl").read_text(encoding="utf-8").splitlines():
            pkgs.add(json.loads(line)["package"])
    return pkgs


def _rec_packages(rec: dict) -> set[str]:
    return {re.sub(r"[-_.]+", "-", a.get("package", {}).get("name", "")).lower() for a in rec.get("affected", [])}


def advisory_chunks() -> tuple[list[str], list[str], list[dict]]:
    """Every advisory for any package in our locks or the benchmark, split into retrievable chunks.

    PYSEC records that duplicate a GHSA record (aliases) are skipped so each bug is indexed once.
    """
    pkgs = _locked_packages()
    recs = advisory.records()
    ids, texts, metas = [], [], []
    seen_alias: set[str] = set()
    ordered = sorted(recs.values(), key=lambda r: (not r["id"].startswith("GHSA"), r["id"]))
    for rec in ordered:
        rp = _rec_packages(rec) & pkgs
        if not rp:
            continue
        names = {rec["id"], *rec.get("aliases", [])}
        if names & seen_alias:
            continue
        seen_alias |= names
        pkg = sorted(rp)[0]
        group = sorted(names)
        ranges = advisory.affected_ranges([rec], pkg)
        meta = {"vuln_id": rec["id"], "package": pkg, "aliases": " ".join(group)}
        head = (f"{rec['id']} ({', '.join(a for a in group if a != rec['id'])})\npackage: {pkg}\n"
                f"summary: {rec.get('summary', '')}\naffected: {'; '.join(ranges)}")
        ids.append(f"{rec['id']}#0")
        texts.append(head)
        metas.append({**meta, "section": "summary"})
        details = (rec.get("details") or "").strip()
        paras = [p.strip() for p in re.split(r"\n\s*\n", details) if p.strip()]
        buf, n = "", 1
        for p in paras:
            if p.lower().startswith(("### references", "## references", "references")):
                break
            if len(buf) + len(p) > 900 and buf:
                ids.append(f"{rec['id']}#{n}")
                texts.append(f"{rec['id']} ({pkg}) details:\n{buf}")
                metas.append({**meta, "section": "details"})
                buf, n = "", n + 1
            buf = f"{buf}\n\n{p}" if buf else p[:2000]
        if buf:
            ids.append(f"{rec['id']}#{n}")
            texts.append(f"{rec['id']} ({pkg}) details:\n{buf}")
            metas.append({**meta, "section": "details"})
    return ids, texts, metas


# ------------------------------------------------------------------ code chunks

@dataclass
class Codebase:
    name: str            # target name, or bench/<case>
    root: Path
    app_dirs: list[str]
    test_dirs: list[str]


def codebases(cfg: Config) -> list[Codebase]:
    out = [Codebase(t.name, t.checkout, t.app_dirs, t.test_dirs) for t in cfg.targets if t.checkout.exists()]
    from ..bench import bench_cases
    for case in bench_cases():
        out.append(Codebase(f"bench/{case['case']}", BENCH / "cases" / case["case"], [], []))
    return out


def code_chunks(cb: Codebase) -> tuple[list[str], list[str], list[dict]]:
    from ..agent.static import _is_test_path
    ids, texts, metas = [], [], []
    for p in iter_py(cb.root, cb.app_dirs or None):
        rel = p.relative_to(cb.root).as_posix()
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        lines = src.splitlines()
        in_test = _is_test_path(rel, cb.test_dirs)
        covered: set[int] = set()

        def emit(qual: str, start: int, end: int, kind: str):
            body = lines[start - 1:min(end, start - 1 + MAX_CHUNK_LINES)]
            text = f"# {rel}:{start}-{end}  {qual}\n" + "\n".join(body)
            ids.append(f"{cb.name}:{rel}:{start}")
            texts.append(text)
            metas.append({"codebase": cb.name, "file": rel, "start": start, "end": end, "qualname": qual,
                          "kind": kind, "in_test": in_test})

        def walk(node, prefix=""):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.FunctionDef | ast.AsyncFunctionDef):
                    emit(f"{prefix}{ch.name}", ch.lineno, ch.end_lineno or ch.lineno, "function")
                    covered.update(range(ch.lineno, (ch.end_lineno or ch.lineno) + 1))
                elif isinstance(ch, ast.ClassDef):
                    walk(ch, f"{prefix}{ch.name}.")
        walk(tree)
        rest = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
        if rest:     # module-level code: imports, settings, route tables
            start, end = rest[0], rest[-1]
            body = [lines[i - 1] for i in rest][:MAX_CHUNK_LINES]
            ids.append(f"{cb.name}:{rel}:module")
            texts.append(f"# {rel} (module level)\n" + "\n".join(body))
            metas.append({"codebase": cb.name, "file": rel, "start": start, "end": end, "qualname": "<module>",
                          "kind": "module", "in_test": in_test})
    return ids, texts, metas


# ------------------------------------------------------------------ build

def build_all(cfg: Config, rebuild: bool = False) -> dict:
    emb = embedder()
    stats = {"embed_model": emb.name, "dim": emb.dim}
    for collection, chunker in [(ADVISORY_COLLECTION, advisory_chunks)]:
        t = time.time()
        ids, texts, metas = chunker()
        vecs = emb.docs(texts)
        for kind in ("chroma", "faiss"):
            open_store(kind, collection, reset=True).add(ids, vecs, texts, metas)
        stats[collection] = {"chunks": len(ids), "seconds": round(time.time() - t, 1)}
        print(f"{collection}: {len(ids)} chunks in {stats[collection]['seconds']}s", file=sys.stderr)
    t = time.time()
    all_ids, all_texts, all_metas = [], [], []
    per = {}
    for cb in codebases(cfg):
        ids, texts, metas = code_chunks(cb)
        per[cb.name] = len(ids)
        all_ids += ids
        all_texts += texts
        all_metas += metas
    vecs = emb.docs(all_texts)
    for kind in ("chroma", "faiss"):
        open_store(kind, CODE_COLLECTION, reset=True).add(all_ids, vecs, all_texts, all_metas)
    stats[CODE_COLLECTION] = {"chunks": len(all_ids), "seconds": round(time.time() - t, 1),
                              "per_codebase": {k: v for k, v in per.items() if not k.startswith("bench/")},
                              "bench_chunks": sum(v for k, v in per.items() if k.startswith("bench/"))}
    print(f"code: {len(all_ids)} chunks in {stats[CODE_COLLECTION]['seconds']}s", file=sys.stderr)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (DATA / "index_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


# ------------------------------------------------------------------ retrieval used by the agent

class Retriever:
    def __init__(self, kind: str = "chroma"):
        self.kind = kind
        self.adv = open_store(kind, ADVISORY_COLLECTION)
        self.code = open_store(kind, CODE_COLLECTION)
        self.emb = embedder()

    def advisory(self, finding: dict, k: int = 4) -> list[Hit]:
        """Chunks of this finding's advisory (by id), plus related advisories for the same package."""
        q = self.emb.query(f"{finding['package']} vulnerable function affected versions: {finding.get('summary', '')}")
        own = []
        for vid in [finding["vuln_id"], *finding.get("aliases", [])]:
            own = self.adv.search(q, k=k, where={"vuln_id": vid})
            if own:
                break
        related = [h for h in self.adv.search(q, k=k + 4, where={"package": finding["package"]})
                   if h.meta["vuln_id"] not in {finding["vuln_id"], *finding.get("aliases", [])}][:2]
        return own + related

    def code_for(self, codebase: str, query: str, k: int = 5) -> list[Hit]:
        return self.code.search(self.emb.query(query), k=k, where={"codebase": codebase})
