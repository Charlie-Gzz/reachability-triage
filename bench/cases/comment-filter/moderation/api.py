from fastapi import FastAPI

from moderation.filters import clean_comment, linkify

app = FastAPI()


@app.post("/comments")
def post_comment(body: dict):
    return {"html": linkify(clean_comment(body["text"]))}
