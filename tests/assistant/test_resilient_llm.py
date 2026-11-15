"""ResilientLLM: structured output with repair (Pattern 3) and model fallback (Pattern 4)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from hr_compass.assistant.domain.answer import RagAnswer
from hr_compass.assistant.infrastructure.resilient_llm import ResilientLLM, parse_model, response_format, schema_name
from hr_compass.shared import openrouter
from hr_compass.shared.llm import LLMError
from hr_compass.shared.openrouter import OpenRouterClient
from hr_compass.shared.settings import FallbackConfig, RetryConfig, Settings, StructuredOutputConfig

GOOD = json.dumps({"found": True, "answer": "3 days", "citations": ["S1"], "confidence": "high",
                   "needs_clarification": False})


def ok_body(text: str, model: str = "m") -> dict:
    return {"model": model, "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(delay):
        return None
    monkeypatch.setattr(openrouter.asyncio, "sleep", instant)


def generate(s: Settings, handler):
    async def go():
        async with OpenRouterClient(s, transport=httpx.MockTransport(handler)) as client:
            return await ResilientLLM(client, s).generate([{"role": "user", "content": "q"}], output_model=RagAnswer)
    return asyncio.run(go())


def settings(**kw) -> Settings:
    defaults = {"api_key": "k", "retry": RetryConfig(max_retries=0),
                "structured_output": StructuredOutputConfig(max_repair_attempts=1), "fallback": FallbackConfig(False)}
    return Settings(**{**defaults, **kw})


def test_the_schema_is_named_after_the_model_and_strict():
    fmt = response_format(RagAnswer, strict=True)
    assert schema_name(RagAnswer) == "rag_answer" and fmt["json_schema"]["name"] == "rag_answer"
    assert fmt["json_schema"]["strict"] is True


def test_parse_accepts_a_fence_and_rejects_invalid_replies():
    assert parse_model(f"```json\n{GOOD}\n```", RagAnswer).citations == ["S1"]
    for bad in ("not json", json.dumps({"found": True, "answer": "x", "citations": [], "confidence": "sure",
                                        "needs_clarification": False})):
        with pytest.raises(ValueError):
            parse_model(bad, RagAnswer)


def test_an_invalid_reply_is_sent_back_and_usage_is_summed():
    bodies: list[dict] = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=ok_body("oops" if len(bodies) == 1 else GOOD))

    result = generate(settings(), handler)

    assert result.parsed.answer == "3 days" and result.completion.prompt_tokens == 20
    assert bodies[0]["response_format"]["json_schema"]["strict"] is True
    assert bodies[1]["messages"][-1]["content"].startswith("Your reply failed validation")


def test_repairs_are_limited():
    with pytest.raises(LLMError, match="invalid structured output after 2 attempt"):
        generate(settings(), lambda _: httpx.Response(200, json=ok_body("never json")))


def fallback(**kw) -> Settings:
    return settings(model="primary", fallback=FallbackConfig(enabled=True, models=("backup-1", "backup-2")), **kw)


def test_fallback_to_the_next_model_on_failure():
    def handler(request):
        model = json.loads(request.content)["model"]
        return (httpx.Response(200, json=ok_body(GOOD, model)) if model == "backup-2"
                else httpx.Response(503, json={"error": {"message": "down"}}))

    result = generate(fallback(), handler)

    assert result.model_used == "backup-2" and result.fallback_used
    assert [f.split(":")[0] for f in result.failures] == ["primary", "backup-1"]


@pytest.mark.parametrize(("status", "retried", "falls_back"), [
    (429, True, True), (500, True, True), (502, True, True), (503, True, True),   # transient: retry, then next model
    (400, False, False), (401, False, False), (403, False, False),                # our request / key: stop
])
def test_error_matrix(status, retried, falls_back):
    models: list[str] = []

    def handler(request):
        models.append(json.loads(request.content)["model"])
        return httpx.Response(status, json={"error": {"message": "x"}})

    s = settings(model="primary", retry=RetryConfig(max_retries=2),
                 fallback=FallbackConfig(enabled=True, models=("backup",)))
    with pytest.raises(LLMError):
        generate(s, handler)
    per_model = 3 if retried else 1
    assert models == ["primary"] * per_model + (["backup"] * per_model if falls_back else [])


def test_all_models_failing_reports_every_failure():
    with pytest.raises(LLMError) as info:
        generate(fallback(), lambda _: httpx.Response(500, json={"error": {"message": "x"}}))
    assert len(info.value.failures) == 3
