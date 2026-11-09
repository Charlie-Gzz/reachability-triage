"""LLM providers: text in, text out. LangGraph orchestrates; the model only reasons at each step.

- `claude-code`: `claude -p` with every tool disabled, one turn, a replaced system prompt, and
  CLAUDE.md / skills / MCP / settings not loaded, run from a neutral temp dir. Uses the existing
  Claude Code login (subscription). Never --bare, never an API key.
- `local`: any OpenAI-compatible endpoint (LM Studio here).
- `mock`: deterministic canned answers driven by the evidence in the prompt, for tests and dev.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import RUNS

T = TypeVar("T", bound=BaseModel)

CLAUDE_CALL_CAP = 1500
LEDGER = RUNS / "_ledger.jsonl"

# Published per-million-token API list prices, used only for an *estimated* API-price equivalent.
PRICES = {"sonnet": (3.0, 15.0), "opus": (15.0, 75.0), "haiku": (1.0, 5.0)}


class UsageLimitError(RuntimeError):
    """Usage, credit, or rate limit hit. The run must stop cleanly, not retry."""


class ProviderError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    model: str = ""
    cost_usd_est: float = 0.0


@dataclass
class CallMeta:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cost_usd_est: float = 0.0
    attempts: list[dict] = field(default_factory=list)

    def add(self, r: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        self.seconds += r.seconds
        self.cost_usd_est += r.cost_usd_est


class Provider:
    name = "base"
    model = ""

    def complete(self, system: str, prompt: str, task: str = "", context: dict | None = None) -> LLMResponse:
        raise NotImplementedError


# --------------------------------------------------------------------------- claude-code

_LIMIT_PAT = re.compile(r"usage limit|rate.?limit|credit|quota|limit reached|too many requests|overloaded_error"
                        r"|out of extra usage|hit your limit", re.I)


def claude_calls_used() -> int:
    if not LEDGER.exists():
        return 0
    return sum(1 for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip())


class ClaudeCodeProvider(Provider):
    name = "claude-code"

    def __init__(self, model: str = "sonnet", timeout: int = 300, label: str = ""):
        self.model = model
        self.timeout = timeout
        self.label = label      # config name, for the ledger
        exe = shutil.which("claude")
        if not exe:
            raise ProviderError("`claude` CLI not found on PATH")
        self.exe = exe

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
                                    "CLAUDE_AGENT_SDK", "ANTHROPIC_API_KEY"))}
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        return env

    def complete(self, system: str, prompt: str, task: str = "", context: dict | None = None) -> LLMResponse:
        if claude_calls_used() >= CLAUDE_CALL_CAP:
            raise UsageLimitError(f"project cap of {CLAUDE_CALL_CAP} Claude calls reached")
        cmd = [self.exe, "-p", "--safe-mode", "--tools", "", "--max-turns", "1",
               "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "",
               "--no-session-persistence", "--model", self.model,
               "--system-prompt", system, "--output-format", "json"]
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="rt-claude-") as cwd:
            try:
                proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", cwd=cwd, env=self._env(), timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                raise ProviderError(f"claude -p timed out after {self.timeout}s") from e
        secs = round(time.monotonic() - start, 2)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            blob = (proc.stdout + proc.stderr)[-1500:]
            if _LIMIT_PAT.search(blob):
                raise UsageLimitError(blob) from None
            raise ProviderError(f"claude -p exit={proc.returncode}: {blob}") from None
        if out.get("is_error") or out.get("subtype") not in (None, "success"):
            blob = json.dumps({k: out.get(k) for k in ("subtype", "result", "api_error_status", "terminal_reason")})
            if out.get("api_error_status") in (429, 529) or _LIMIT_PAT.search(blob):
                raise UsageLimitError(blob)
            raise ProviderError(blob)
        u = out.get("usage", {})
        tin = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        tout = u.get("output_tokens", 0)
        pin, pout = PRICES.get(self.model, PRICES["sonnet"])
        resolved = next((m for m in out.get("modelUsage", {}) if "haiku" not in m), self.model)
        r = LLMResponse(text=out.get("result", ""), input_tokens=tin, output_tokens=tout, seconds=secs,
                        model=resolved, cost_usd_est=round((tin * pin + tout * pout) / 1e6, 6))
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "config": self.label,
                                "task": task, "model": resolved, "in": tin, "out": tout, "s": secs}) + "\n")
        return r


# --------------------------------------------------------------------------- local

class LocalProvider(Provider):
    name = "local"

    def __init__(self, base_url: str, model: str, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, prompt: str, task: str = "", context: dict | None = None) -> LLMResponse:
        start = time.monotonic()
        try:
            r = httpx.post(f"{self.base_url}/v1/chat/completions", timeout=self.timeout, json={
                "model": self.model, "temperature": 0, "max_tokens": 2048,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise ProviderError(f"local model timed out after {self.timeout}s") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"local model error: {e}") from e
        body = r.json()
        u = body.get("usage", {})
        return LLMResponse(text=body["choices"][0]["message"]["content"], input_tokens=u.get("prompt_tokens", 0),
                           output_tokens=u.get("completion_tokens", 0), seconds=round(time.monotonic() - start, 2),
                           model=self.model)


def discover_local(ports=(1234, 11434, 8080, 1337, 1235), want=("qwen2.5-coder-14b",)) -> tuple[str, str] | None:
    for port in ports:
        url = f"http://localhost:{port}"
        try:
            models = httpx.get(f"{url}/v1/models", timeout=3).json().get("data", [])
        except (httpx.HTTPError, ValueError):
            continue
        for m in models:
            if any(w in m.get("id", "").lower() for w in want):
                return url, m["id"]
    return None


# --------------------------------------------------------------------------- mock

class MockProvider(Provider):
    """Deterministic, evidence-driven answers. Good enough to exercise every graph branch."""
    name = "mock"
    model = "mock"

    def complete(self, system: str, prompt: str, task: str = "", context: dict | None = None) -> LLMResponse:
        ctx = context or {}
        if task == "verdict":
            calls = ctx.get("vulnerable_call_sites", 0)
            imported = ctx.get("imported", False)
            if calls:
                v, conf = "reachable", 0.8
            elif not imported:
                v, conf = "not_reachable", 0.85
            elif ctx.get("symbols"):
                v, conf = "not_reachable", 0.6
            else:
                v, conf = "uncertain", 0.4
            ev = ctx.get("evidence_locations", [])[:3]
            text = json.dumps({"verdict": v, "confidence": conf, "reasoning": f"mock: {calls} call sites, imported={imported}",
                               "evidence": [{"location": e, "explanation": "static evidence"} for e in ev],
                               "vulnerable_symbols": ctx.get("symbols", [])[:5]})
        elif task == "reflection":
            v = ctx.get("verdict", "uncertain")
            text = json.dumps({"agrees": True, "final_verdict": v, "confidence": ctx.get("confidence", 0.5),
                               "critique": "mock: evidence is consistent with the verdict", "retry": False})
        elif task == "test":
            text = json.dumps({"test_path": "tests/test_rt_vuln.py", "test_id": "tests/test_rt_vuln.py::test_vuln",
                               "code": "def test_vuln():\n    assert False, 'mock'\n", "rationale": "mock"})
        elif task == "patch":
            text = json.dumps({"files": [], "rationale": "mock: no patch"})
        else:
            text = json.dumps({"ok": True})
        return LLMResponse(text=text, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4, seconds=0.0,
                           model="mock")


# --------------------------------------------------------------------------- structured output

def _extract_json(text: str) -> str:
    text = text.strip()
    if m := re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S):
        return m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def structured(provider: Provider, system: str, prompt: str, schema: type[T], task: str,
               context: dict | None = None) -> tuple[T | None, CallMeta, str | None]:
    """Ask for JSON matching `schema`. Retry once with the validation error; then give up with parse_error.

    Returns (parsed or None, meta, error). UsageLimitError propagates so the run can stop cleanly.
    """
    meta = CallMeta()
    shape = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    full = f"{prompt}\n\nRespond with ONE JSON object only, no prose, matching this JSON Schema:\n{shape}"
    err = None
    for attempt in range(2):
        try:
            r = provider.complete(system, full, task=task, context=context)
        except ProviderError as e:
            err = f"provider_error: {e}"[:500]
            meta.attempts.append({"attempt": attempt, "error": err})
            continue
        meta.add(r)
        meta.attempts.append({"attempt": attempt, "raw": r.text[:4000], "in": r.input_tokens, "out": r.output_tokens,
                              "s": r.seconds, "model": r.model})
        try:
            return schema.model_validate_json(_extract_json(r.text)), meta, None
        except ValidationError as e:
            err = "parse_error"
            full = (f"{prompt}\n\nYour previous answer was not valid. Validation error:\n{str(e)[:1500]}\n\n"
                    f"Respond with ONE JSON object only, matching this JSON Schema:\n{shape}")
    return None, meta, err


# --------------------------------------------------------------------------- factory + check

def make(spec: dict, label: str = "") -> Provider:
    kind = spec.get("provider", "mock")
    if kind == "mock":
        return MockProvider()
    if kind == "claude-code":
        return ClaudeCodeProvider(model=spec.get("model", "sonnet"), label=label)
    if kind == "local":
        return LocalProvider(spec["base_url"], spec["model"], timeout=spec.get("timeout", 300))
    raise ValueError(f"unknown provider {kind!r}")


def check_all(only: str | None = None) -> dict:
    class Ping(BaseModel):
        ok: bool
        n: int

    status = {}
    candidates: list[tuple[str, callable]] = [("mock", MockProvider)]
    candidates.append(("claude-code", lambda: ClaudeCodeProvider(label="provider-check")))
    found = discover_local()
    if found:
        candidates.append(("local", lambda: LocalProvider(*found)))
    else:
        status["local"] = "unavailable: no OpenAI-compatible endpoint lists a Qwen2.5 Coder 14B model"
    for name, ctor in candidates:
        if only and name != only:
            continue
        try:
            p = ctor()
            if name == "mock":
                status[name] = "ok"
                continue
            obj, meta, err = structured(p, "You are a terse assistant.", 'Return ok=true and n=2+2.', Ping, task="ping")
            status[name] = (f"ok ({p.model}, {meta.input_tokens} in / {meta.output_tokens} out tokens, {meta.seconds:.1f}s)"
                            if obj and obj.n == 4 else f"answered but wrong/invalid: {err} {meta.attempts[-1:]}")
        except Exception as e:  # report, don't crash
            status[name] = f"error: {e}"[:300]
    for k, v in status.items():
        print(f"{k:12} {v}")
    return status
