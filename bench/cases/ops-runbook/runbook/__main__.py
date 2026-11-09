import sys

from runbook.engine import run_book

if __name__ == "__main__":
    n = run_book(sys.argv[1], dry_run="--dry-run" in sys.argv)
    print(f"{n} steps")
