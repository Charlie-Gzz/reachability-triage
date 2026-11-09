import json

from flask import Flask, request

from pipeline.jobs import run_job

app = Flask(__name__)


@app.post("/jobs")
def submit_job():
    steps = json.loads(request.form["steps"])
    return run_job(request.files["image"].read(), steps), 200, {"Content-Type": "image/png"}
