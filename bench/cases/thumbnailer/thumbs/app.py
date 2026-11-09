from flask import Flask, request

from thumbs.worker import make_thumbnails

app = Flask(__name__)


@app.post("/thumbnails")
def thumbnails():
    sizes = make_thumbnails(request.files["image"].read())
    return {k: len(v) for k, v in sizes.items()}
