from flask import Flask, jsonify, request

from recipes.importer import parse_recipe
from recipes.store import save_recipe

app = Flask(__name__)


@app.route("/recipes/import", methods=["POST"])
def import_recipe():
    recipe = parse_recipe(request.get_data(as_text=True))
    recipe_id = save_recipe(recipe)
    return jsonify({"id": recipe_id}), 201


@app.route("/health")
def health():
    return "ok"
