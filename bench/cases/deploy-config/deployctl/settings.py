from pathlib import Path

import yaml

CONFIG_DIR = Path("environments")


def load_settings(env: str) -> dict:
    path = CONFIG_DIR / f"{env}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def write_settings(env: str, settings: dict) -> None:
    path = CONFIG_DIR / f"{env}.yaml"
    path.write_text(yaml.safe_dump(settings, sort_keys=True))
