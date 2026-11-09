"""Kept for the old nightly job (removed in 2023)."""
import ujson


def write_export_ujson(rows, path):
    with open(path, "w") as f:
        ujson.dump(rows, f, ensure_ascii=False)
