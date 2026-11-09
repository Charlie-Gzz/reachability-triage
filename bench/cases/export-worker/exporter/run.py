import json
import sys

from exporter.query import fetch_rows


def export(table: str, out_path: str) -> int:
    rows = fetch_rows(table)
    with open(out_path, "w") as f:
        json.dump(rows, f, default=str)
    return len(rows)


if __name__ == "__main__":
    print(export(sys.argv[1], sys.argv[2]))
