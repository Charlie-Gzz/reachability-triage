from flask import Flask, jsonify, request

from widgets.templating import render_reply

app = Flask(__name__)


@app.route("/macros/preview", methods=["POST"])
def preview_macro():
    body = request.get_json()
    return jsonify({"html": render_reply(body["template"], body.get("ticket", {}))})
