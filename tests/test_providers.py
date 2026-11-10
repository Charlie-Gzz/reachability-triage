"""Structured-output retry logic with scripted fake providers. No `claude` CLI, no network."""
import pytest
from pydantic import BaseModel

from reachability_triage.agent.providers import (
    LLMResponse,
    MockProvider,
    Provider,
    ProviderError,
    UsageLimitError,
    _extract_json,
    structured,
)


class Ping(BaseModel):
    ok: bool
    n: int


class Scripted(Provider):
    """Returns (or raises) each scripted item in turn and records the prompts it saw."""
    name = "scripted"

    def __init__(self, *items):
        self.items = list(items)
        self.prompts = []

    def complete(self, system, prompt, task="", context=None):
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, input_tokens=10, output_tokens=5, seconds=0.1, model="m")


def test_extract_json_handles_fences_and_prose():
    assert _extract_json('```json\n{"ok": true, "n": 4}\n```') == '{"ok": true, "n": 4}'
    assert _extract_json('Sure! {"ok": true, "n": 4} hope that helps') == '{"ok": true, "n": 4}'
    assert _extract_json("no json here") == "no json here"


def test_valid_first_answer_is_one_call():
    p = Scripted('{"ok": true, "n": 4}')
    obj, meta, err = structured(p, "sys", "q", Ping, task="ping")
    assert obj == Ping(ok=True, n=4) and err is None
    assert meta.calls == 1 and meta.input_tokens == 10 and meta.attempts[0]["model"] == "m"


def test_invalid_then_valid_retries_once_with_the_validation_error():
    p = Scripted('{"ok": "maybe"}', '{"ok": true, "n": 4}')
    obj, meta, err = structured(p, "sys", "q", Ping, task="ping")
    assert obj.n == 4 and err is None and meta.calls == 2
    assert "not valid" in p.prompts[1] and "Validation error" in p.prompts[1]


def test_two_invalid_answers_give_parse_error():
    p = Scripted("nope", '{"n": "x"}')
    obj, meta, err = structured(p, "sys", "q", Ping, task="ping")
    assert obj is None and err == "parse_error" and meta.calls == 2


def test_provider_error_is_retried_then_reported():
    p = Scripted(ProviderError("boom"), ProviderError("boom again"))
    obj, meta, err = structured(p, "sys", "q", Ping, task="ping")
    assert obj is None and meta.calls == 0
    assert err.startswith("provider_error: boom again") and len(meta.attempts) == 2


def test_provider_error_then_success():
    obj, meta, err = structured(Scripted(ProviderError("t/o"), '{"ok": false, "n": 1}'), "s", "q", Ping, task="p")
    assert obj == Ping(ok=False, n=1) and err is None and meta.calls == 1


def test_usage_limit_propagates_so_the_run_stops():
    with pytest.raises(UsageLimitError):
        structured(Scripted(UsageLimitError("hit your limit")), "sys", "q", Ping, task="ping")


@pytest.mark.parametrize("ctx, verdict", [
    ({"vulnerable_call_sites": 2, "imported": True}, "reachable"),
    ({"vulnerable_call_sites": 0, "imported": False}, "not_reachable"),
    ({"vulnerable_call_sites": 0, "imported": True, "symbols": ["x"]}, "not_reachable"),
    ({"vulnerable_call_sites": 0, "imported": True}, "uncertain"),
])
def test_mock_provider_verdicts(ctx, verdict):
    import json
    r = MockProvider().complete("s", "p", task="verdict", context=ctx)
    assert json.loads(r.text)["verdict"] == verdict
