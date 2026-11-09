import yaml

REQUIRED = ("title", "ingredients", "steps")


def parse_recipe(text: str) -> dict:
    """Recipes are shared as YAML exports from the mobile app."""
    data = yaml.load(text, Loader=yaml.FullLoader)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"missing fields: {missing}")
    return data
