"""Playwright screenshots of the case explorer and the review page (headless, dark, 1440px wide).

The review page is shot read-only: we never click a label button, so no label is marked reviewed.
"""
from __future__ import annotations

import contextlib
import functools
import http.server
import json
import socket
import sys
import threading

from ..config import ASSETS, SITE

OUT = ASSETS / "screenshots"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _static_server(root):
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


@contextlib.contextmanager
def _review_server():
    from ..review.server import Handler
    port = _free_port()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


def _featured() -> list[dict]:
    text = (SITE / "data" / "index.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))["featured"]


def take_screenshots() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  screenshots skipped: playwright not installed", file=sys.stderr)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1, color_scheme="dark")
        with _static_server(SITE) as base:
            shots = [("overview", "index.html", True), ("findings", "findings.html?config=full", False)]
            shots += [(f"case-{i + 1}", f"case.html?id={f['slug']}", True) for i, f in enumerate(_featured())]
            for name, url, full in shots:
                page.goto(f"{base}/{url}", wait_until="networkidle")
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
                print(f"  screenshot {name}", file=sys.stderr)
        with _review_server() as base:
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT / "review.png"))
            print("  screenshot review", file=sys.stderr)
        b.close()
