import json
from pathlib import Path

from billing.client import StripeLikeClient


def sync_plans(plans_file: str) -> int:
    plans = json.loads(Path(plans_file).read_text())
    client = StripeLikeClient()
    for plan in plans:
        client.upsert_plan(plan["id"], plan["amount"], plan["interval"])
    return len(plans)


if __name__ == "__main__":
    import sys
    print(sync_plans(sys.argv[1]))
