from flask import Flask, request

from sessions.auth import new_session, read_session

app = Flask(__name__)


@app.post("/login")
def login():
    return {"token": new_session(int(request.form["user_id"]))}


@app.get("/whoami")
def whoami():
    return read_session(request.headers["X-Session"])
