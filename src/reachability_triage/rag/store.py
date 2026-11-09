"""Embeddings + one retrieval interface over two vector stores (Chroma = main, FAISS = benchmark)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import WORK

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
INDEX_DIR = WORK / "index"


class Embedder:
    def __init__(self, model: str = EMBED_MODEL):
        from sentence_transformers import SentenceTransformer
        self.name = model
        self.model = SentenceTransformer(model, device="cpu")
        self.dim = self.model.get_sentence_embedding_dimension()

    def docs(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        return np.asarray(self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                            show_progress_bar=len(texts) > 500), dtype="float32")

    def query(self, text: str) -> np.ndarray:
        return np.asarray(self.model.encode([QUERY_PREFIX + text], normalize_embeddings=True), dtype="float32")[0]


@lru_cache(maxsize=1)
def embedder() -> Embedder:
    return Embedder()


@dataclass
class Hit:
    id: str
    score: float
    text: str
    meta: dict


class VectorStore:
    kind = "base"

    def add(self, ids: list[str], vecs: np.ndarray, texts: list[str], metas: list[dict]) -> None: ...

    def search(self, vec: np.ndarray, k: int = 5, where: dict | None = None) -> list[Hit]: ...

    def count(self) -> int: ...


def _match(meta: dict, where: dict | None) -> bool:
    return not where or all(meta.get(k) == v for k, v in where.items())


class ChromaStore(VectorStore):
    kind = "chroma"

    def __init__(self, collection: str, path: Path = INDEX_DIR / "chroma", reset: bool = False):
        import chromadb
        from chromadb.config import Settings
        self.client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        if reset:
            try:
                self.client.delete_collection(collection)
            except Exception:
                pass
        self.col = self.client.get_or_create_collection(collection, metadata={"hnsw:space": "cosine"})

    def add(self, ids, vecs, texts, metas):
        for i in range(0, len(ids), 2000):
            self.col.add(ids=ids[i:i + 2000], embeddings=vecs[i:i + 2000].tolist(), documents=texts[i:i + 2000],
                         metadatas=metas[i:i + 2000])

    def search(self, vec, k=5, where=None):
        if len(where or {}) > 1:
            where = {"$and": [{kk: vv} for kk, vv in where.items()]}
        r = self.col.query(query_embeddings=[vec.tolist()], n_results=k, where=where or None)
        return [Hit(i, 1 - d, t, m) for i, d, t, m in
                zip(r["ids"][0], r["distances"][0], r["documents"][0], r["metadatas"][0], strict=False)]

    def count(self):
        return self.col.count()


class FaissStore(VectorStore):
    """Exact inner-product search (vectors are normalised, so = cosine). Metadata filter = post-filter."""
    kind = "faiss"

    def __init__(self, collection: str, path: Path = INDEX_DIR / "faiss", reset: bool = False):
        import faiss
        self.faiss = faiss
        self.path = path / collection
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.metas: list[dict] = []
        self.index = None
        if not reset and (self.path / "index.faiss").exists():
            self.index = faiss.read_index(str(self.path / "index.faiss"))
            side = json.loads((self.path / "meta.json").read_text(encoding="utf-8"))
            self.ids, self.texts, self.metas = side["ids"], side["texts"], side["metas"]

    def add(self, ids, vecs, texts, metas):
        if self.index is None:
            self.index = self.faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(vecs)
        self.ids += ids
        self.texts += texts
        self.metas += metas
        self.path.mkdir(parents=True, exist_ok=True)
        self.faiss.write_index(self.index, str(self.path / "index.faiss"))
        (self.path / "meta.json").write_text(json.dumps({"ids": self.ids, "texts": self.texts, "metas": self.metas}),
                                             encoding="utf-8")

    def search(self, vec, k=5, where=None):
        if self.index is None or not self.ids:
            return []
        fetch = min(len(self.ids), k if not where else max(k * 50, 500))
        while True:
            scores, idx = self.index.search(vec.reshape(1, -1), fetch)
            hits = [Hit(self.ids[i], float(s), self.texts[i], self.metas[i])
                    for s, i in zip(scores[0], idx[0], strict=False) if i >= 0 and _match(self.metas[i], where)]
            if len(hits) >= k or fetch >= len(self.ids):
                return hits[:k]
            fetch = min(len(self.ids), fetch * 4)

    def count(self):
        return len(self.ids)


def open_store(kind: str, collection: str, reset: bool = False) -> VectorStore:
    return (ChromaStore if kind == "chroma" else FaissStore)(collection, reset=reset)


def timed_search(store: VectorStore, vec, k=5, where=None) -> tuple[list[Hit], float]:
    t = time.perf_counter()
    hits = store.search(vec, k, where)
    return hits, (time.perf_counter() - t) * 1000
