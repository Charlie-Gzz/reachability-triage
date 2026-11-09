from flask import Blueprint, request

from comments.sanitize import sanitize

bp = Blueprint("comments", __name__)
COMMENTS = []


@bp.post("/threads/<int:thread_id>/comments")
def add_comment(thread_id):
    COMMENTS.append({"thread": thread_id, "html": sanitize(request.form["body"])})
    return {"count": len(COMMENTS)}, 201
