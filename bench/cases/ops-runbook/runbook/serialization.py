import yaml


def load_document(stream):
    """Shared loader so every runbook format goes through one place."""
    return yaml.full_load(stream)


def dump_document(data) -> str:
    return yaml.safe_dump(data)
