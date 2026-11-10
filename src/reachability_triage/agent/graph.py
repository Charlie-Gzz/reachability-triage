"""The reachability agent as a LangGraph state graph.

load_finding -> retrieve_advisory -> static_evidence -> retrieve_code -> verdict -> reflect
reflect --(weak evidence, retry once)--> verdict
reflect --(route)--> suppress | flag_for_human | remediate (handled by remediate/ when enabled)

Every node appends a step record (inputs, outputs, tokens, latency) to state["steps"]; the run record
written to runs/<config>/ is exactly that state, minus internals. Labels are never loaded here.
"""
from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import advisory, prompts, static
from .providers import Provider, structured
from .schemas import Reflection, Verdict


class TriageState(TypedDict, total=False):
    finding: dict
    codebase: dict                 # {name, root, app_dirs, test_dirs, template_dirs}
    options: dict                  # {retrieval, reflection, max_retries}
    advisory_chunks: list[dict]
    symbols: list[str]
    evidence: dict
    code_chunks: list[dict]
    verdict: dict
    reflection: dict
    attempts: int
    critique: str | None
    final: dict
    errors: Annotated[list[str], operator.add]
    steps: Annotated[list[dict], operator.add]


def _step(name: str, start: float, output: Any, meta=None, **extra) -> dict:
    d = {"node": name, "ms": round((time.perf_counter() - start) * 1000, 1), "output": output,
         "tokens_in": getattr(meta, "input_tokens", 0), "tokens_out": getattr(meta, "output_tokens", 0),
         "llm_calls": getattr(meta, "calls", 0), "llm_seconds": round(getattr(meta, "seconds", 0.0), 2),
         "cost_usd_est": round(getattr(meta, "cost_usd_est", 0.0), 6)}
    if meta is not None:
        d["attempts"] = meta.attempts
    d.update(extra)
    return d


def build_graph(provider: Provider, retriever=None):
    def load_finding(s: TriageState):
        t = time.perf_counter()
        f = s["finding"]
        return {"attempts": 0, "critique": None,
                "steps": [_step("scanner_alert", t, {k: f.get(k) for k in (
                    "finding_id", "package", "version", "vuln_id", "aliases", "summary", "max_cvss",
                    "fixed_versions", "direct_dependency")})]}

    def retrieve_advisory(s: TriageState):
        t = time.perf_counter()
        f = s["finding"]
        imports = s["codebase"]["import_names"]
        chunks = []
        if s["options"].get("retrieval", True) and retriever is not None:
            hits = retriever.advisory(f)
            chunks = [{"id": h.id, "score": round(h.score, 3), "text": h.text, "vuln_id": h.meta.get("vuln_id")}
                      for h in hits]
            own = {f["vuln_id"], *f.get("aliases", [])}
            text = "\n".join(c["text"] for c in chunks if c["vuln_id"] in own) or f.get("summary", "")
            symbols = advisory.extract_symbols(text, imports, f["package"])
        else:
            symbols = advisory.symbols_for(f, [], imports, summary_only=True)
        return {"advisory_chunks": chunks, "symbols": symbols,
                "steps": [_step("advisory_retrieved", t, {"chunks": chunks, "symbols": symbols,
                                                          "retrieval": bool(chunks)})]}

    def static_evidence(s: TriageState):
        t = time.perf_counter()
        cb = s["codebase"]
        ev = static.gather(cb["root"], cb["app_dirs"], cb["test_dirs"], s["finding"]["package"],
                           cb["import_names"], s["symbols"], cb.get("template_dirs"))
        d = ev.to_dict()
        for site in d["vulnerable_call_sites"][:8]:
            if not site["in_test"]:
                site["snippet"] = static.function_source(cb["root"], site["file"], site["line"], 3)
        return {"evidence": d, "steps": [_step("static_evidence", t, d)]}

    def retrieve_code(s: TriageState):
        t = time.perf_counter()
        chunks = []
        if s["options"].get("retrieval", True) and retriever is not None:
            f = s["finding"]
            q = f"{f['package']} {' '.join(s['symbols'][:5])} {f.get('summary', '')}"
            hits = retriever.code_for(s["codebase"]["name"], q, k=5)
            chunks = [{"id": h.id, "score": round(h.score, 3), "text": h.text, "file": h.meta["file"],
                       "start": h.meta["start"], "qualname": h.meta["qualname"]} for h in hits]
            # Always include the code around production call sites (the call path), ahead of similarity hits.
            seen = {c["file"] + str(c["start"]) for c in chunks}
            for site in s["evidence"]["vulnerable_call_sites"][:4]:
                if site.get("snippet") and (site["file"] + str(site["line"])) not in seen:
                    chunks.insert(0, {"id": f"site:{site['file']}:{site['line']}", "score": 1.0, "file": site["file"],
                                      "start": site["line"], "qualname": site["function"],
                                      "text": f"# {site['file']} around line {site['line']}\n{site['snippet']}"})
            chunks = chunks[:7]
        return {"code_chunks": chunks, "steps": [_step("code_context", t, {"chunks": chunks})]}

    def verdict(s: TriageState):
        t = time.perf_counter()
        ctx = _mock_context(s)
        obj, meta, err = structured(provider, prompts.VERDICT_SYSTEM, prompts.verdict_prompt(s, s.get("critique")),
                                    Verdict, task="verdict", context=ctx)
        if obj is None:
            v = {"verdict": "uncertain", "confidence": 0.0, "reasoning": f"no valid verdict: {err}",
                 "evidence": [], "vulnerable_symbols": [], "error": err}
        else:
            v = obj.model_dump()
        return {"verdict": v, "attempts": s.get("attempts", 0) + 1,
                "errors": [err] if err else [],
                "steps": [_step("verdict", t, v, meta, attempt=s.get("attempts", 0) + 1)]}

    def reflect(s: TriageState):
        t = time.perf_counter()
        v = s["verdict"]
        if v.get("error"):          # nothing to critique; keep parse_error visible
            r = {"agrees": True, "final_verdict": "uncertain", "confidence": 0.0, "retry": False,
                 "critique": "skipped: verdict could not be parsed", "skipped": True}
            return {"reflection": r, "steps": [_step("reflection", t, r)]}
        obj, meta, err = structured(provider, prompts.REFLECT_SYSTEM, prompts.reflect_prompt(s), Reflection,
                                    task="reflection", context={"verdict": v["verdict"], "confidence": v["confidence"]})
        if obj is None:
            r = {"agrees": True, "final_verdict": v["verdict"], "confidence": v["confidence"], "retry": False,
                 "critique": f"reflection failed ({err}); verdict kept", "error": err}
        else:
            r = obj.model_dump()
        out = {"reflection": r, "errors": [err] if err else [], "steps": [_step("reflection", t, r, meta)]}
        if r.get("retry") and s.get("attempts", 1) <= s["options"].get("max_retries", 1):
            out["critique"] = r["critique"]
        return out

    def route_after_reflect(s: TriageState) -> str:
        r = s.get("reflection", {})
        if r.get("retry") and s.get("attempts", 1) <= s["options"].get("max_retries", 1):
            return "verdict"
        return "decide"

    def route_after_verdict(s: TriageState) -> str:
        return "reflect" if s["options"].get("reflection", True) else "decide"

    def decide(s: TriageState):
        t = time.perf_counter()
        v, r = s["verdict"], s.get("reflection")
        final_label = r["final_verdict"] if r else v["verdict"]
        conf = r["confidence"] if r else v["confidence"]
        reason = "parse_error" if v.get("error") == "parse_error" else (v.get("error") or None)
        action = {"reachable": "remediate", "not_reachable": "suppress", "uncertain": "flag_for_human"}[final_label]
        final = {"verdict": final_label, "confidence": conf, "action": action, "uncertain_reason": reason,
                 "changed_by_reflection": bool(r) and final_label != v["verdict"], "verdict_attempts": s["attempts"]}
        return {"final": final, "steps": [_step(action, t, final)]}

    g = StateGraph(TriageState)
    g.add_node("load_finding", load_finding)
    g.add_node("retrieve_advisory", retrieve_advisory)
    g.add_node("static_evidence", static_evidence)
    g.add_node("retrieve_code", retrieve_code)
    g.add_node("verdict", verdict)
    g.add_node("reflect", reflect)
    g.add_node("decide", decide)
    g.add_edge(START, "load_finding")
    g.add_edge("load_finding", "retrieve_advisory")
    g.add_edge("retrieve_advisory", "static_evidence")
    g.add_edge("static_evidence", "retrieve_code")
    g.add_edge("retrieve_code", "verdict")
    g.add_conditional_edges("verdict", route_after_verdict, {"reflect": "reflect", "decide": "decide"})
    g.add_conditional_edges("reflect", route_after_reflect, {"verdict": "verdict", "decide": "decide"})
    g.add_edge("decide", END)
    return g.compile()


def _mock_context(s: TriageState) -> dict:
    ev = s["evidence"]
    prod = [x for x in ev["vulnerable_call_sites"] if not x["in_test"] and not x["weak"]]
    return {"vulnerable_call_sites": len(prod) + len(ev["config_references"]) + len(ev["template_references"]),
            "imported": ev["imported"], "symbols": s["symbols"],
            "evidence_locations": [f"{x['file']}:{x['line']}" for x in prod] + ev["import_locations"]}
