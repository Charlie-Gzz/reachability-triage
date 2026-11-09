import subprocess

from runbook.serialization import load_document


def run_book(path: str, dry_run: bool = False) -> int:
    with open(path) as f:
        book = load_document(f)
    for step in book.get("steps", []):
        print(f"-> {step['name']}")
        if not dry_run:
            subprocess.run(step["run"], shell=True, check=True)
    return len(book.get("steps", []))
