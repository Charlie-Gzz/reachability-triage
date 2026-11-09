from fastapi import APIRouter
from pydantic import BaseModel

from console.formatting import normalize

router = APIRouter()
AUDIT = []


class Query(BaseModel):
    sql: str


@router.post("/console/run")
def run_query(q: Query):
    AUDIT.append(normalize(q.sql))
    return {"queued": True, "position": len(AUDIT)}
