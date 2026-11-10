"""Generates bench/cases/* and bench/labels.jsonl. Ground truth is fixed here, when each case is built.

Run: uv run python bench/build_cases.py .   (the agent never reads this file; it only sees bench/cases/<case>/)
"""
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
CASES = ROOT / "bench" / "cases"

C = []  # (case, package, version, vuln_id, label, category, split, vulnerable_location, notes, files)


def case(name, pkg, ver, vid, label, cat, split, loc, notes, files, extra_reqs=()):
    C.append(dict(case=name, package=pkg, version=ver, vuln_id=vid, label=label, category=cat, split=split,
                  evidence=loc, notes=notes, files=files, reqs=[f"{pkg}=={ver}", *extra_reqs]))


# ----------------------------------------------------------------- pyyaml 5.3.1 / FullLoader RCE
case("recipe-importer", "pyyaml", "5.3.1", "GHSA-8q59-q68h-6hv4", "reachable", "direct_call", "dev",
     "recipes/importer.py:9", "POST /recipes/import parses the uploaded body with FullLoader.", {
         "app.py": '''from flask import Flask, jsonify, request

from recipes.importer import parse_recipe
from recipes.store import save_recipe

app = Flask(__name__)


@app.route("/recipes/import", methods=["POST"])
def import_recipe():
    recipe = parse_recipe(request.get_data(as_text=True))
    recipe_id = save_recipe(recipe)
    return jsonify({"id": recipe_id}), 201


@app.route("/health")
def health():
    return "ok"
''',
         "recipes/__init__.py": "",
         "recipes/importer.py": '''import yaml

REQUIRED = ("title", "ingredients", "steps")


def parse_recipe(text: str) -> dict:
    """Recipes are shared as YAML exports from the mobile app."""
    data = yaml.load(text, Loader=yaml.FullLoader)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise ValueError(f"missing fields: {missing}")
    return data
''',
         "recipes/store.py": '''import uuid

_RECIPES: dict[str, dict] = {}


def save_recipe(recipe: dict) -> str:
    rid = uuid.uuid4().hex
    _RECIPES[rid] = recipe
    return rid
''',
     }, ["flask==2.0.3"])

case("deploy-config", "pyyaml", "5.3.1", "GHSA-8q59-q68h-6hv4", "not_reachable", "safe_api_only", "dev",
     "", "Only yaml.safe_load / safe_dump are used; the advisory is about FullLoader / full_load.", {
         "deployctl/__init__.py": "",
         "deployctl/cli.py": '''import argparse

from deployctl.settings import load_settings, write_settings


def main(argv=None):
    p = argparse.ArgumentParser(prog="deployctl")
    p.add_argument("env")
    p.add_argument("--set", nargs=2, action="append", default=[])
    args = p.parse_args(argv)
    settings = load_settings(args.env)
    for key, value in args.set:
        settings[key] = value
    write_settings(args.env, settings)
    print(f"{args.env}: {len(settings)} keys")


if __name__ == "__main__":
    main()
''',
         "deployctl/settings.py": '''from pathlib import Path

import yaml

CONFIG_DIR = Path("environments")


def load_settings(env: str) -> dict:
    path = CONFIG_DIR / f"{env}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def write_settings(env: str, settings: dict) -> None:
    path = CONFIG_DIR / f"{env}.yaml"
    path.write_text(yaml.safe_dump(settings, sort_keys=True))
''',
     })

case("ops-runbook", "pyyaml", "5.3.1", "GHSA-8q59-q68h-6hv4", "reachable", "indirect_call", "test",
     "runbook/serialization.py:6", "CLI -> run_book() -> load_document() wrapper -> yaml.full_load.", {
         "runbook/__init__.py": "",
         "runbook/serialization.py": '''import yaml


def load_document(stream):
    """Shared loader so every runbook format goes through one place."""
    return yaml.full_load(stream)


def dump_document(data) -> str:
    return yaml.safe_dump(data)
''',
         "runbook/engine.py": '''import subprocess

from runbook.serialization import load_document


def run_book(path: str, dry_run: bool = False) -> int:
    with open(path) as f:
        book = load_document(f)
    for step in book.get("steps", []):
        print(f"-> {step['name']}")
        if not dry_run:
            subprocess.run(step["run"], shell=True, check=True)
    return len(book.get("steps", []))
''',
         "runbook/__main__.py": '''import sys

from runbook.engine import run_book

if __name__ == "__main__":
    n = run_book(sys.argv[1], dry_run="--dry-run" in sys.argv)
    print(f"{n} steps")
''',
     })

case("billing-sync", "pyyaml", "5.3.1", "GHSA-8q59-q68h-6hv4", "not_reachable", "dead_code", "dev",
     "billing/legacy.py:7", "full_load only in import_v1_plans(), which nothing calls (v1 import was retired).", {
         "billing/__init__.py": "",
         "billing/sync.py": '''import json
from pathlib import Path

from billing.client import StripeLikeClient


def sync_plans(plans_file: str) -> int:
    plans = json.loads(Path(plans_file).read_text())
    client = StripeLikeClient()
    for plan in plans:
        client.upsert_plan(plan["id"], plan["amount"], plan["interval"])
    return len(plans)


if __name__ == "__main__":
    import sys
    print(sync_plans(sys.argv[1]))
''',
         "billing/client.py": '''class StripeLikeClient:
    def __init__(self):
        self.plans = {}

    def upsert_plan(self, plan_id, amount, interval):
        self.plans[plan_id] = {"amount": amount, "interval": interval}
''',
         "billing/legacy.py": '''"""Format used by the 2019 billing system."""
import yaml


def import_v1_plans(path):
    with open(path) as f:
        doc = yaml.full_load(f)
    return [{"id": p["code"], "amount": p["cents"], "interval": p["period"]} for p in doc["plans"]]
''',
     })

# ----------------------------------------------------------------- jinja2 2.10
case("newsletter-render", "jinja2", "2.10", "GHSA-h5c8-rqwp-cp95", "reachable", "direct_call", "test",
     "templates/signup.html:3", "Route passes user-chosen attribute keys into the xmlattr filter.", {
         "app.py": '''from flask import Flask, render_template, request

app = Flask(__name__)


@app.route("/embed/signup")
def signup_widget():
    # Partners customise the embedded form; extra query params become <form> attributes.
    attrs = {k: v for k, v in request.args.items() if k != "list"}
    return render_template("signup.html", list_id=request.args.get("list", "main"), attrs=attrs)
''',
         "templates/signup.html": '''<!doctype html>
<div class="signup">
  <form method="post" action="/subscribe"{{ attrs|xmlattr }}>
    <input type="hidden" name="list" value="{{ list_id }}">
    <input type="email" name="email" placeholder="you@example.com">
    <button>Subscribe</button>
  </form>
</div>
''',
     }, ["flask==2.0.3"])

case("docs-portal", "jinja2", "2.10", "GHSA-462w-v97r-4m45", "not_reachable", "safe_api_only", "test",
     "", "Plain Environment rendering the project's own templates; the bug is a SandboxedEnvironment escape.", {
         "portal/__init__.py": "",
         "portal/render.py": '''from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(loader=FileSystemLoader("theme"), autoescape=select_autoescape(["html"]))


def render_page(page: dict, nav: list) -> str:
    template = env.get_template(page.get("layout", "page.html"))
    return template.render(page=page, nav=nav)


def build(pages: list, out_dir: str = "public") -> None:
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    nav = [{"title": p["title"], "slug": p["slug"]} for p in pages]
    for page in pages:
        (out / f"{page['slug']}.html").write_text(render_page(page, nav))
''',
         "portal/__main__.py": '''import json
import sys

from portal.render import build

if __name__ == "__main__":
    build(json.load(open(sys.argv[1])))
''',
     })

case("support-widgets", "jinja2", "2.10", "GHSA-462w-v97r-4m45", "reachable", "indirect_call", "dev",
     "widgets/templating.py:12", "Customer-authored reply templates are rendered in a SandboxedEnvironment; the advisory is a sandbox escape via str.format.", {
         "app.py": '''from flask import Flask, jsonify, request

from widgets.templating import render_reply

app = Flask(__name__)


@app.route("/macros/preview", methods=["POST"])
def preview_macro():
    body = request.get_json()
    return jsonify({"html": render_reply(body["template"], body.get("ticket", {}))})
''',
         "widgets/__init__.py": "",
         "widgets/templating.py": '''from jinja2.sandbox import SandboxedEnvironment

# Support agents write their own reply macros, so templates are untrusted input.
_env = SandboxedEnvironment(autoescape=True)


def render_reply(source: str, ticket: dict) -> str:
    template = _env.from_string(source)
    return template.render(ticket=ticket, agent={"name": "Support"})


def render_reply_safe(source: str, ticket: dict) -> str:
    return _env.from_string(source).render(ticket=ticket)
''',
     }, ["flask==2.0.3"])

# ----------------------------------------------------------------- pillow 8.0.0 / ImageMath.eval
case("metrics-dashboard", "pillow", "8.0.0", "GHSA-8vj2-vxx3-667w", "reachable", "direct_call", "test",
     "dashboard/bands.py:10", "User-supplied band expression goes straight into ImageMath.eval.", {
         "dashboard/__init__.py": "",
         "dashboard/api.py": '''from fastapi import FastAPI, UploadFile

from dashboard.bands import composite

app = FastAPI()


@app.post("/satellite/composite")
async def satellite_composite(image: UploadFile, expression: str = "(a - b) / (a + b)"):
    data = await image.read()
    return {"png": composite(data, expression)}
''',
         "dashboard/bands.py": '''import base64
import io

from PIL import Image, ImageMath


def composite(raw: bytes, expression: str) -> str:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    r, g, b = img.split()
    result = ImageMath.eval(expression, a=r, b=g, c=b)
    out = io.BytesIO()
    result.convert("L").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()
''',
     }, ["fastapi==0.95.2"])

case("thumbnailer", "pillow", "8.0.0", "GHSA-8vj2-vxx3-667w", "not_reachable", "safe_api_only", "test",
     "", "Only Image.open/thumbnail/save; ImageMath is never imported.", {
         "thumbs/__init__.py": "",
         "thumbs/worker.py": '''import io

from PIL import Image

SIZES = {"sm": (128, 128), "md": (512, 512)}


def make_thumbnails(raw: bytes) -> dict:
    out = {}
    for name, size in SIZES.items():
        img = Image.open(io.BytesIO(raw))
        img.thumbnail(size)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        out[name] = buf.getvalue()
    return out
''',
         "thumbs/app.py": '''from flask import Flask, request

from thumbs.worker import make_thumbnails

app = Flask(__name__)


@app.post("/thumbnails")
def thumbnails():
    sizes = make_thumbnails(request.files["image"].read())
    return {k: len(v) for k, v in sizes.items()}
''',
     }, ["flask==2.0.3"])

case("photo-pipeline", "pillow", "8.0.0", "GHSA-8vj2-vxx3-667w", "reachable", "indirect_call", "test",
     "pipeline/ops/expressions.py:5", "Route -> run_job() -> dispatch table OPS['expr'] -> apply_expression() -> ImageMath.eval.", {
         "pipeline/__init__.py": "",
         "pipeline/ops/__init__.py": '''from pipeline.ops.basic import grayscale, resize
from pipeline.ops.expressions import apply_expression

OPS = {"resize": resize, "grayscale": grayscale, "expr": apply_expression}
''',
         "pipeline/ops/basic.py": '''def resize(img, width, height):
    return img.resize((int(width), int(height)))


def grayscale(img):
    return img.convert("L")
''',
         "pipeline/ops/expressions.py": '''from PIL import ImageMath


def apply_expression(img, formula):
    return ImageMath.eval(formula, a=img.convert("L"))
''',
         "pipeline/jobs.py": '''import io

from PIL import Image

from pipeline.ops import OPS


def run_job(raw: bytes, steps: list) -> bytes:
    img = Image.open(io.BytesIO(raw))
    for step in steps:
        img = OPS[step["op"]](img, *step.get("args", []))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
''',
         "pipeline/server.py": '''import json

from flask import Flask, request

from pipeline.jobs import run_job

app = Flask(__name__)


@app.post("/jobs")
def submit_job():
    steps = json.loads(request.form["steps"])
    return run_job(request.files["image"].read(), steps), 200, {"Content-Type": "image/png"}
''',
     }, ["flask==2.0.3"])

# ----------------------------------------------------------------- lxml 4.6.2 / Cleaner formaction XSS
# POST-HOC CORRECTION (2026-11-09, see docs/DECISIONS.md): originally labelled reachable/direct_call. The advisory
# needs BOTH forms and safe_attrs_only disabled; this app keeps safe_attrs_only=True, and lxml 4.6.2 run in a
# container strips formaction under this exact config. Code unchanged; label corrected.
case("comments-hub", "lxml", "4.6.2", "GHSA-jq4v-f5q6-mjqq", "not_reachable", "config_disabled", "test",
     "comments/sanitize.py:9", "Cleaner is used on user HTML with forms=False but safe_attrs_only=True; the advisory "
     "requires both disabled, and lxml 4.6.2 strips formaction under this config (verified in a container).", {
         "comments/__init__.py": "",
         "comments/sanitize.py": '''from lxml.html.clean import Cleaner

_cleaner = Cleaner(scripts=True, javascript=True, style=True, forms=False, safe_attrs_only=True)


def sanitize(html: str) -> str:
    if not html.strip():
        return ""
    return _cleaner.clean_html(html)
''',
         "comments/views.py": '''from flask import Blueprint, request

from comments.sanitize import sanitize

bp = Blueprint("comments", __name__)
COMMENTS = []


@bp.post("/threads/<int:thread_id>/comments")
def add_comment(thread_id):
    COMMENTS.append({"thread": thread_id, "html": sanitize(request.form["body"])})
    return {"count": len(COMMENTS)}, 201
''',
     }, ["flask==2.0.3"])

case("feed-reader", "lxml", "4.6.2", "GHSA-jq4v-f5q6-mjqq", "not_reachable", "safe_api_only", "dev",
     "", "Parses RSS with lxml.etree only; the HTML Cleaner is never used.", {
         "reader/__init__.py": "",
         "reader/feeds.py": '''import urllib.request

from lxml import etree


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()


def parse_items(xml: bytes) -> list:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml, parser)
    return [{"title": i.findtext("title"), "link": i.findtext("link")} for i in root.iter("item")]
''',
         "reader/__main__.py": '''import sys

from reader.feeds import fetch, parse_items

for item in parse_items(fetch(sys.argv[1])):
    print(f"{item['title']}  {item['link']}")
''',
     })

# ----------------------------------------------------------------- sqlparse 0.4.1 / StripComments ReDoS
case("query-console", "sqlparse", "0.4.1", "GHSA-p5w8-wqhj-9hhf", "reachable", "direct_call", "test",
     "console/formatting.py:6", "User SQL is formatted with strip_comments=True (the vulnerable filter).", {
         "console/__init__.py": "",
         "console/formatting.py": '''import sqlparse


def normalize(sql: str) -> str:
    """Strip comments so the audit log stores just the statement."""
    return sqlparse.format(sql, strip_comments=True, reindent=False).strip()
''',
         "console/routes.py": '''from fastapi import APIRouter
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
''',
     }, ["fastapi==0.95.2"])

case("sql-linter", "sqlparse", "0.4.1", "GHSA-p5w8-wqhj-9hhf", "not_reachable", "config_disabled", "dev",
     "lint/format.py:5", "sqlparse.format is called, but without strip_comments, so the vulnerable StripComments filter never runs.", {
         "lint/__init__.py": "",
         "lint/format.py": '''import sqlparse


def pretty(sql: str) -> str:
    return sqlparse.format(sql, reindent=True, keyword_case="upper", identifier_case="lower")


def statements(sql: str) -> list:
    return [s for s in sqlparse.split(sql) if s.strip()]
''',
         "lint/cli.py": '''import sys

from lint.format import pretty, statements


def main():
    sql = open(sys.argv[1]).read()
    for stmt in statements(sql):
        print(pretty(stmt))
        print()


if __name__ == "__main__":
    main()
''',
     })

# ----------------------------------------------------------------- pyjwt 1.7.1 / key confusion
case("auth-gateway", "pyjwt", "1.7.1", "GHSA-ffqj-6fqr-9h24", "reachable", "config_enabled", "test",
     "gateway/tokens.py:10", "jwt.decode with algorithms=get_default_algorithms() mixes HMAC and asymmetric algorithms: the exact condition in the advisory.", {
         "gateway/__init__.py": "",
         "gateway/tokens.py": '''import os

import jwt
from jwt.algorithms import get_default_algorithms

PUBLIC_KEY = os.environ.get("ISSUER_PUBLIC_KEY", "")


def verify(token: str) -> dict:
    # Upstream issuers sign with RS256 or ES256 depending on the tenant.
    return jwt.decode(token, PUBLIC_KEY, algorithms=list(get_default_algorithms()))
''',
         "gateway/middleware.py": '''from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from gateway.tokens import verify


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        header = request.headers.get("authorization", "")
        try:
            request.state.claims = verify(header.removeprefix("Bearer "))
        except Exception:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
''',
         "gateway/app.py": '''from fastapi import FastAPI, Request

from gateway.middleware import AuthMiddleware

app = FastAPI()
app.add_middleware(AuthMiddleware)


@app.get("/me")
def me(request: Request):
    return request.state.claims
''',
     }, ["fastapi==0.95.2"])

case("session-service", "pyjwt", "1.7.1", "GHSA-ffqj-6fqr-9h24", "not_reachable", "config_disabled", "test",
     "sessions/auth.py:8", "jwt.decode pins algorithms=['HS256'] with a shared secret, so the HMAC/public-key confusion can't happen.", {
         "sessions/__init__.py": "",
         "sessions/auth.py": '''import os
import time

import jwt

SECRET = os.environ.get("SESSION_SECRET", "dev-secret")


def read_session(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def new_session(user_id: int) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
''',
         "sessions/views.py": '''from flask import Flask, request

from sessions.auth import new_session, read_session

app = Flask(__name__)


@app.post("/login")
def login():
    return {"token": new_session(int(request.form["user_id"]))}


@app.get("/whoami")
def whoami():
    return read_session(request.headers["X-Session"])
''',
     }, ["flask==2.0.3"])

# ----------------------------------------------------------------- aiohttp 3.9.1 / follow_symlinks traversal
case("static-host", "aiohttp", "3.9.1", "GHSA-5h86-8mv2-jq9f", "reachable", "config_enabled", "dev",
     "host/server.py:11", "add_static(..., follow_symlinks=True): the advisory's vulnerable configuration.", {
         "host/__init__.py": "",
         "host/server.py": '''from pathlib import Path

from aiohttp import web

SITE_ROOT = Path("/srv/sites")


def make_app() -> web.Application:
    app = web.Application()
    # Customer sites are symlinked in from the build cache.
    app.router.add_static("/sites", SITE_ROOT, follow_symlinks=True, show_index=False)
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=8080)
''',
     })

case("asset-server", "aiohttp", "3.9.1", "GHSA-5h86-8mv2-jq9f", "not_reachable", "config_disabled", "test",
     "assets/app.py:9", "add_static with the default follow_symlinks=False; the traversal needs follow_symlinks=True.", {
         "assets/__init__.py": "",
         "assets/app.py": '''from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).parent / "static"


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_static("/static", STATIC)
    app.router.add_get("/", index)
    return app


async def index(request):
    return web.FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    web.run_app(create_app())
''',
     })

# ----------------------------------------------------------------- gitpython 3.1.29 / clone_from RCE
case("repo-mirror", "gitpython", "3.1.29", "GHSA-hcpj-qp55-gfph", "reachable", "direct_call", "test",
     "mirror/service.py:10", "API takes a repository URL from the request and calls Repo.clone_from on it.", {
         "mirror/__init__.py": "",
         "mirror/service.py": '''import tempfile
from pathlib import Path

from git import Repo

MIRRORS = Path(tempfile.gettempdir()) / "mirrors"


def create_mirror(url: str, name: str) -> str:
    dest = MIRRORS / name
    Repo.clone_from(url, dest, mirror=True)
    return str(dest)
''',
         "mirror/api.py": '''from fastapi import FastAPI
from pydantic import BaseModel

from mirror.service import create_mirror

app = FastAPI()


class MirrorRequest(BaseModel):
    url: str
    name: str


@app.post("/mirrors")
def add_mirror(req: MirrorRequest):
    return {"path": create_mirror(req.url, req.name)}
''',
     }, ["fastapi==0.95.2"])

case("changelog-bot", "gitpython", "3.1.29", "GHSA-hcpj-qp55-gfph", "not_reachable", "imported_not_called", "dev",
     "", "Reads commits from the local repo with Repo('.').iter_commits; never clones.", {
         "changelog/__init__.py": "",
         "changelog/collect.py": '''import re

from git import Repo

TYPES = {"feat": "Features", "fix": "Fixes", "perf": "Performance"}


def commits_since(tag: str, path: str = "."):
    repo = Repo(path)
    return list(repo.iter_commits(f"{tag}..HEAD"))


def group(commits) -> dict:
    out = {v: [] for v in TYPES.values()}
    for c in commits:
        m = re.match(r"(\\w+)(\\(.+\\))?: (.+)", c.summary)
        if m and m.group(1) in TYPES:
            out[TYPES[m.group(1)]].append(m.group(3))
    return out
''',
         "changelog/__main__.py": '''import sys

from changelog.collect import commits_since, group

for section, items in group(commits_since(sys.argv[1])).items():
    if items:
        print(f"## {section}")
        print("\\n".join(f"- {i}" for i in items))
''',
     })

# ----------------------------------------------------------------- django 3.2.0 / order_by SQLi
DJ_SETTINGS = '''SECRET_KEY = "dev"
DEBUG = False
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "{app}"]
ROOT_URLCONF = "{app}.urls"
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}}}}
'''
case("article-api", "django", "3.2.0", "GHSA-xpfp-f569-q3p2", "reachable", "direct_call", "test",
     "articles/views.py:8", "Sort column comes from ?sort= and goes straight into QuerySet.order_by.", {
         "manage.py": '''import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "articles.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
''',
         "articles/__init__.py": "",
         "articles/settings.py": DJ_SETTINGS.format(app="articles"),
         "articles/models.py": '''from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=200)
    published = models.DateTimeField()
    views = models.IntegerField(default=0)
''',
         "articles/views.py": '''from django.http import JsonResponse

from articles.models import Article


def article_list(request):
    sort = request.GET.get("sort", "-published")
    rows = Article.objects.order_by(sort).values("id", "title", "published")[:50]
    return JsonResponse({"results": list(rows)})
''',
         "articles/urls.py": '''from django.urls import path

from articles import views

urlpatterns = [path("articles/", views.article_list)]
''',
     })

case("inventory-api", "django", "3.2.0", "GHSA-xpfp-f569-q3p2", "not_reachable", "config_disabled", "test",
     "stock/views.py:12", "order_by is only ever called with an allow-listed column, never raw user input.", {
         "manage.py": '''import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
''',
         "stock/__init__.py": "",
         "stock/settings.py": DJ_SETTINGS.format(app="stock"),
         "stock/models.py": '''from django.db import models


class Item(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    quantity = models.IntegerField()
    updated = models.DateTimeField(auto_now=True)
''',
         "stock/views.py": '''from django.http import JsonResponse

from stock.models import Item

SORTABLE = {"sku": "sku", "qty": "-quantity", "recent": "-updated"}


def item_list(request):
    key = request.GET.get("sort", "recent")
    if key not in SORTABLE:
        key = "recent"
    items = Item.objects.order_by(SORTABLE[key]).values("sku", "quantity")
    return JsonResponse({"items": list(items)})
''',
         "stock/urls.py": '''from django.urls import path

from stock import views

urlpatterns = [path("items/", views.item_list)]
''',
     })

# ----------------------------------------------------------------- paramiko 2.9.2 / key file race
case("key-rotation", "paramiko", "2.9.2", "GHSA-f8q4-jwww-x3wv", "reachable", "direct_call", "dev",
     "rotate/keys.py:9", "The rotate CLI writes new private keys with write_private_key_file.", {
         "rotate/__init__.py": "",
         "rotate/keys.py": '''from pathlib import Path

import paramiko


def generate(path: Path, bits: int = 3072) -> str:
    key = paramiko.RSAKey.generate(bits)
    path.parent.mkdir(parents=True, exist_ok=True)
    key.write_private_key_file(str(path))
    return f"{key.get_name()} {key.get_base64()}"
''',
         "rotate/cli.py": '''import argparse
from pathlib import Path

from rotate.keys import generate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("host")
    p.add_argument("--dir", default="~/.ssh/rotated")
    args = p.parse_args()
    pub = generate(Path(args.dir).expanduser() / args.host)
    print(pub)


if __name__ == "__main__":
    main()
''',
     })

case("ssh-inventory", "paramiko", "2.9.2", "GHSA-f8q4-jwww-x3wv", "not_reachable", "imported_not_called", "test",
     "", "Uses SSHClient to run commands; never writes private keys.", {
         "inventory/__init__.py": "",
         "inventory/collect.py": '''import paramiko

COMMANDS = {"kernel": "uname -r", "uptime": "uptime -p", "disk": "df -h /"}


def collect(host: str, user: str) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.load_system_host_keys()
    client.connect(host, username=user, timeout=10)
    try:
        out = {}
        for name, cmd in COMMANDS.items():
            _, stdout, _ = client.exec_command(cmd)
            out[name] = stdout.read().decode().strip()
        return out
    finally:
        client.close()
''',
         "inventory/__main__.py": '''import json
import sys

from inventory.collect import collect

print(json.dumps({h: collect(h, "ops") for h in sys.argv[1:]}, indent=2))
''',
     })

# ----------------------------------------------------------------- ujson 4.0.1 / dump leak
case("export-worker", "ujson", "4.0.1", "GHSA-c38f-wx89-p2xg", "not_reachable", "dead_code", "test",
     "exporter/compat.py:8", "ujson.dump only in write_export_ujson(), left over from a migration and never called; exports use stdlib json.", {
         "exporter/__init__.py": "",
         "exporter/run.py": '''import json
import sys

from exporter.query import fetch_rows


def export(table: str, out_path: str) -> int:
    rows = fetch_rows(table)
    with open(out_path, "w") as f:
        json.dump(rows, f, default=str)
    return len(rows)


if __name__ == "__main__":
    print(export(sys.argv[1], sys.argv[2]))
''',
         "exporter/query.py": '''import sqlite3


def fetch_rows(table: str) -> list:
    con = sqlite3.connect("warehouse.db")
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]  # table names come from our own config
''',
         "exporter/compat.py": '''"""Kept for the old nightly job (removed in 2023)."""
import ujson


def write_export_ujson(rows, path):
    with open(path, "w") as f:
        ujson.dump(rows, f, ensure_ascii=False)
''',
     })

# ----------------------------------------------------------------- bleach 3.1.0 / noscript mXSS
case("notes-app", "bleach", "3.1.0", "GHSA-q65m-pv3f-wr5r", "reachable", "config_enabled", "test",
     "notes/render.py:9", "bleach.clean allows noscript plus a raw-text tag (style) with strip=False: the advisory's condition.", {
         "notes/__init__.py": "",
         "notes/render.py": '''import bleach
import markdown

TAGS = ["p", "a", "b", "i", "ul", "ol", "li", "code", "pre", "noscript", "style", "h1", "h2", "h3"]
ATTRS = {"a": ["href", "title"]}


def render_note(source: str) -> str:
    html = markdown.markdown(source)
    return bleach.clean(html, tags=TAGS, attributes=ATTRS, strip=False)
''',
         "notes/web.py": '''from flask import Flask, request

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
''',
     }, ["flask==2.0.3", "markdown==3.3.4"])

case("comment-filter", "bleach", "3.1.0", "GHSA-q65m-pv3f-wr5r", "not_reachable", "config_disabled", "dev",
     "moderation/filters.py:7", "bleach.clean with a small allow-list (no noscript, no raw-text tags) and strip=True.", {
         "moderation/__init__.py": "",
         "moderation/filters.py": '''import bleach

ALLOWED = ["b", "i", "em", "strong", "a"]


def clean_comment(text: str) -> str:
    return bleach.clean(text, tags=ALLOWED, attributes={"a": ["href"]}, strip=True)


def linkify(text: str) -> str:
    return bleach.linkify(text)
''',
         "moderation/api.py": '''from fastapi import FastAPI

from moderation.filters import clean_comment, linkify

app = FastAPI()


@app.post("/comments")
def post_comment(body: dict):
    return {"html": linkify(clean_comment(body["text"]))}
''',
     }, ["fastapi==0.95.2"])

# ----------------------------------------------------------------- nltk 3.6.5 / tokenizer ReDoS
case("tagger-service", "nltk", "3.6.5", "GHSA-f8m6-h2c7-8h9x", "reachable", "direct_call", "test",
     "tagger/nlp.py:5", "word_tokenize on raw request text.", {
         "tagger/__init__.py": "",
         "tagger/nlp.py": '''from nltk import pos_tag, word_tokenize


def tag(text: str) -> list:
    tokens = word_tokenize(text)
    return [{"token": t, "pos": p} for t, p in pos_tag(tokens)]
''',
         "tagger/api.py": '''from fastapi import FastAPI
from pydantic import BaseModel

from tagger.nlp import tag

app = FastAPI()


class Doc(BaseModel):
    text: str


@app.post("/tag")
def tag_doc(doc: Doc):
    return {"tags": tag(doc.text)}
''',
     }, ["fastapi==0.95.2"])

case("corpus-tools", "nltk", "3.6.5", "GHSA-f8m6-h2c7-8h9x", "not_reachable", "test_only", "test",
     "tests/test_counts.py:3", "Production code splits on whitespace; word_tokenize is only used in a test to cross-check counts.", {
         "corpus/__init__.py": "",
         "corpus/stats.py": '''from collections import Counter


def tokens(text: str) -> list:
    return [t.strip(".,;:!?\\"'()").lower() for t in text.split() if t.strip(".,;:!?\\"'()")]


def top_words(text: str, n: int = 20) -> list:
    return Counter(tokens(text)).most_common(n)
''',
         "corpus/__main__.py": '''import sys

from corpus.stats import top_words

for word, count in top_words(open(sys.argv[1]).read()):
    print(f"{count:>6}  {word}")
''',
         "tests/test_counts.py": '''from corpus.stats import tokens

from nltk.tokenize import word_tokenize


def test_counts_close_to_nltk():
    text = "The quick brown fox jumps over the lazy dog."
    assert abs(len(tokens(text)) - len([t for t in word_tokenize(text) if t.isalpha()])) <= 1
''',
     })

# ----------------------------------------------------------------- setuptools 65.4.0 / package_index ReDoS
case("release-tool", "setuptools", "65.4.0", "GHSA-r9hx-vwmv-q579", "not_reachable", "safe_api_only", "test",
     "", "Uses setuptools.setup / find_packages and pkg_resources only; package_index is never touched.", {
         "setup.py": '''from setuptools import find_packages, setup

setup(name="release-tool", version="1.4.0", packages=find_packages(), entry_points={
    "console_scripts": ["release=release.cli:main"]})
''',
         "release/__init__.py": "",
         "release/cli.py": '''import argparse

import pkg_resources

from release.bump import bump


def main():
    p = argparse.ArgumentParser()
    p.add_argument("part", choices=["major", "minor", "patch"])
    args = p.parse_args()
    current = pkg_resources.get_distribution("release-tool").version
    print(bump(current, args.part))


if __name__ == "__main__":
    main()
''',
         "release/bump.py": '''def bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
''',
     })


PATTERNS = {
    "recipe-importer": "yaml.load(", "ops-runbook": "yaml.full_load", "billing-sync": "yaml.full_load",
    "newsletter-render": "xmlattr", "support-widgets": "_env.from_string(source)\n" and "template = _env.from_string",
    "metrics-dashboard": "ImageMath.eval", "photo-pipeline": "ImageMath.eval", "comments-hub": "clean_html",
    "query-console": "strip_comments=True", "sql-linter": "sqlparse.format", "auth-gateway": "jwt.decode",
    "session-service": "jwt.decode", "static-host": "follow_symlinks=True", "asset-server": "add_static",
    "repo-mirror": "clone_from", "article-api": "order_by", "inventory-api": "order_by",
    "key-rotation": "write_private_key_file", "export-worker": "ujson.dump", "notes-app": "bleach.clean",
    "comment-filter": "bleach.clean", "tagger-service": "word_tokenize(text)", "corpus-tools": "word_tokenize(text)",
}


def main():
    import shutil
    if CASES.exists():
        shutil.rmtree(CASES)
    labels = []
    for c in C:
        d = CASES / c["case"]
        for rel, text in c["files"].items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        (d / "requirements.txt").write_text("\n".join(c["reqs"]) + "\n", encoding="utf-8", newline="\n")
        if c["evidence"]:
            rel = c["evidence"].rsplit(":", 1)[0]
            lines = (d / rel).read_text(encoding="utf-8").splitlines()
            pat = PATTERNS[c["case"]]
            n = next(i for i, l in enumerate(lines, 1) if pat in l)
            c["evidence"] = f"{rel}:{n}"
        labels.append({k: c[k] for k in ("case", "package", "version", "vuln_id", "label", "category", "split",
                                         "evidence", "notes")})
    (ROOT / "bench" / "labels.jsonl").write_text("".join(json.dumps(l, sort_keys=True) + "\n" for l in labels),
                                                encoding="utf-8", newline="\n")
    from collections import Counter
    print(len(labels), "cases;", Counter((l["split"], l["label"]) for l in labels))


main()
