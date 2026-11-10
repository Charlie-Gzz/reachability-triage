"""Prompts. Tuned only on the benchmark's `dev` split (see docs/DECISIONS.md); never on `test` or real labels."""
from __future__ import annotations

VERDICT_SYSTEM = """You are a senior application-security engineer triaging dependency-scanner alerts.
For one alert, decide whether the vulnerable code in the dependency is REACHABLE from this application.

Definitions:
- reachable: the application's production code exercises the vulnerable function, feature, or configuration the
  advisory describes (directly, through wrappers, framework hooks, templates, or settings), and an outside
  party can plausibly influence that path where the advisory requires it.
- not_reachable: the vulnerable function/feature is never used by production code: the package is not imported,
  only unaffected parts of it are used, the vulnerable call only exists in tests or in code nothing calls, or the
  app uses it in a configuration the advisory states is not affected.
- uncertain: the evidence cannot settle it either way (for example the advisory names no function and the package
  is used broadly, or the vulnerable behaviour sits deep inside a framework the app relies on).

Rules:
- Base the verdict on the evidence given. Cite file:line locations from it. Do not invent code you were not shown.
- Wrongly marking a real issue not_reachable is the most expensive mistake. Use not_reachable only when the
  evidence positively shows the vulnerable part is unused or safely configured; otherwise reachable or uncertain.
- A package that is a core framework (Django, Flask, Werkzeug, Starlette, FastAPI, SQLAlchemy, Jinja2 as the
  template engine) is used on every request: decide on whether the app uses the specific vulnerable feature.
- Static call-site matching is name-based. A "weak" match may be an unrelated method with the same name.
- This is an application, not a library: code that nothing in the project calls (and that is not a route, view,
  task, CLI command, signal handler or other framework-registered entry point) is dead code. "Someone could call
  it later" is not a path. If the only vulnerable use is in dead code or tests, the verdict is not_reachable.
"""

REFLECT_SYSTEM = """You are reviewing another engineer's reachability verdict for a dependency vulnerability.
Argue against the verdict as hard as the evidence allows, then decide whether it stands.
- If the verdict is not_reachable, look for any path the evidence shows into the vulnerable feature (wrappers,
  dispatch tables, middleware, templates, settings, configuration flags). A false suppression is the costliest error.
- If the verdict is reachable, check the advisory's preconditions (specific function, option, or configuration)
  are actually met by the cited code.
- Set retry=true only when the verdict clearly ignored or misread a specific piece of evidence.
- final_verdict is your decision after the critique; use uncertain when the evidence genuinely cannot decide.
"""


def fmt_finding(f: dict) -> str:
    return (f"Alert: {f['vuln_id']} ({', '.join(a for a in f.get('aliases', []) if a != f['vuln_id'])})\n"
            f"Package: {f['package']}=={f['version']} ({'direct' if f.get('direct_dependency') else 'transitive'} "
            f"dependency); fixed in: {', '.join(f.get('fixed_versions', [])) or 'unknown'}\n"
            f"Scanner summary: {f.get('summary', '')}\nCWE: {', '.join(f.get('cwes', [])) or 'n/a'}")


def verdict_prompt(state: dict, critique: str | None = None) -> str:
    parts = ["## Scanner alert", fmt_finding(state["finding"])]
    if state.get("advisory_chunks"):
        parts += ["## Advisory (retrieved)"] + [c["text"][:1800] for c in state["advisory_chunks"]]
    ev = state["evidence"]
    sr = ev.get("searched", {})
    parts += ["## Static evidence (AST analysis of the application)", ev["summary"],
              f"Searched for the symbols: {sr.get('python_files', '?')} first-party Python files (calls, attribute "
              "references, keyword arguments, and string literals such as Django MIDDLEWARE / INSTALLED_APPS / "
              f"settings values) and {sr.get('template_files', 0)} HTML template files"
              + (f" under {', '.join(sr['template_dirs'])}" if sr.get("template_dirs") else "")
              + " (filter use like `|name`). Zero matches therefore means none of these places use the symbol."]
    if ev["import_locations"]:
        parts.append("Imports: " + ", ".join(ev["import_locations"][:10]))
    for s in ev["vulnerable_call_sites"][:12]:
        tag = "TEST" if s["in_test"] else ("weak name-only match" if s["weak"] else "call/reference")
        path = (" path from entry point: " + " -> ".join(s["path"])) if s["path"] else (
            "" if s["in_test"] else " no caller chain from an entry point found"
            + (" (the enclosing function has NO callers anywhere in the project)" if s.get("callers") == 0 else ""))
        parts.append(f"- {s['file']}:{s['line']} [{tag}] in {s['function']}: `{s['code']}`{path}")
    for u in ev.get("package_usages", [])[:10]:
        if not any(u["location"] == f"{s['file']}:{s['line']}" for s in ev["vulnerable_call_sites"]):
            parts.append(f"- other use of the package {u['location']}{' [TEST]' if u['in_test'] else ''}: `{u['code']}`")
    for c in ev["config_references"][:6]:
        parts.append(f"- config/string reference {c['location']}: {c['value']!r}")
    for t in ev["template_references"][:6]:
        parts.append(f"- template use {t['location']}: {t['symbol']}")
    if state.get("code_chunks"):
        parts.append("## Application code (retrieved by similarity to the advisory)")
        for c in state["code_chunks"]:
            parts.append(f"```python\n{c['text'][:1500]}\n```")
    if critique:
        parts += ["## Reviewer critique of your previous verdict (address it)", critique]
    parts.append("Decide reachability for THIS application.")
    return "\n\n".join(parts)


def reflect_prompt(state: dict) -> str:
    v = state["verdict"]
    return (verdict_prompt(state) + "\n\n## Verdict under review\n"
            + f"verdict={v['verdict']} confidence={v['confidence']}\nreasoning: {v['reasoning']}\n"
            + "evidence:\n" + "\n".join(f"- {e['location']}: {e['explanation']}" for e in v.get("evidence", [])))
