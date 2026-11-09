from flask import Flask, request

from notes.render import render_note

app = Flask(__name__)
NOTES = {}


@app.put("/notes/<slug>")
def save(slug):
    NOTES[slug] = render_note(request.get_data(as_text=True))
    return {"ok": True}


@app.get("/notes/<slug>")
def show(slug):
    return NOTES.get(slug, "")
