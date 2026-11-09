"""Format used by the 2019 billing system."""
import yaml


def import_v1_plans(path):
    with open(path) as f:
        doc = yaml.full_load(f)
    return [{"id": p["code"], "amount": p["cents"], "interval": p["period"]} for p in doc["plans"]]
