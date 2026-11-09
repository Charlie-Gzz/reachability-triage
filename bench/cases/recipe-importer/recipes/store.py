import uuid

_RECIPES: dict[str, dict] = {}


def save_recipe(recipe: dict) -> str:
    rid = uuid.uuid4().hex
    _RECIPES[rid] = recipe
    return rid
