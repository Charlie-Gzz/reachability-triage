from fastapi import FastAPI
from pydantic import BaseModel

from tagger.nlp import tag

app = FastAPI()


class Doc(BaseModel):
    text: str


@app.post("/tag")
def tag_doc(doc: Doc):
    return {"tags": tag(doc.text)}
