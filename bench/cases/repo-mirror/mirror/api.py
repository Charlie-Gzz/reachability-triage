from fastapi import FastAPI
from pydantic import BaseModel

from mirror.service import create_mirror

app = FastAPI()


class MirrorRequest(BaseModel):
    url: str
    name: str


@app.post("/mirrors")
def add_mirror(req: MirrorRequest):
    return {"path": create_mirror(req.url, req.name)}
