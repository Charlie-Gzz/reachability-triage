from flask import Flask, render_template, request

app = Flask(__name__)


@app.route("/embed/signup")
def signup_widget():
    # Partners customise the embedded form; extra query params become <form> attributes.
    attrs = {k: v for k, v in request.args.items() if k != "list"}
    return render_template("signup.html", list_id=request.args.get("list", "main"), attrs=attrs)
