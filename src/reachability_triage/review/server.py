"""`rt review`: a local page to confirm drafted real-set labels fast. Saves to data/labels.jsonl.

Stdlib http.server only, bound to 127.0.0.1. The page never shows the agent's verdicts, so the review
isn't anchored on the model being evaluated.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..eval.draft_labels import load_labels, save_labels

PAGE = Path(__file__).with_name("review.html")
_lock = threading.Lock()


def _items() -> list[dict]:
    from ..agent import advisory
    from ..agent.runner import real_findings
    labels = load_labels()
    out = []
    for f in real_findings():
        if f["finding_id"] not in labels:
            continue
        recs = advisory.for_finding(f)
        main = recs[0] if recs else {}
        out.append({"finding": f, "label": labels[f["finding_id"]],
                    "advisory": {"id": main.get("id"), "summary": main.get("summary", ""),
                                 "details": (main.get("details") or "")[:6000],
                                 "references": [r.get("url") for r in main.get("references", [])][:6],
                                 "affected": advisory.affected_ranges(recs, f["package"])}})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/items":
            self._send(200, json.dumps(_items()).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/label":
            return self._send(404, b"not found", "text/plain")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if body.get("label") not in ("reachable", "not_reachable", "uncertain"):
            return self._send(400, b"bad label", "text/plain")
        with _lock:
            labels = load_labels()
            d = labels.get(body["finding_id"])
            if d is None:
                return self._send(404, b"unknown finding", "text/plain")
            d.update({"label": body["label"], "status": "reviewed", "notes": body.get("notes", ""),
                      "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                      "review_action": "confirmed" if body["label"] == d["drafted_label"] else "changed"})
            save_labels(labels)
        self._send(200, json.dumps(d).encode(), "application/json")


def serve(port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    labels = load_labels()
    pending = sum(1 for d in labels.values() if d["status"] != "reviewed")
    print(f"Label review: {url}  ({pending} of {len(labels)} pending).  Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped; labels are saved after every click in data/labels.jsonl")
