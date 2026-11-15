"""The OpenRouter gateway: timeouts, retries with backoff, error handling, /rerank, logging without the key."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
import pytest

from hr_compass.knowledge.infrastructure.rerankers import OpenRouterReranker
from hr_compass.shared import openrouter
from hr_compass.shared.openrouter import OpenRouterClient, OpenRouterError
from hr_compass.shared.settings import ConfigError, RetryConfig, Settings, TimeoutConfig

REAL_SLEEP = asyncio.sleep   # captured before the autouse fixture patches it
TIMING = re.compile(r"attempt_time=\d+\.\d\ds total=\d+\.\d\ds")


def settings(**overrides) -> Settings:
    return Settings(**{"api_key": "test-key", "retry": RetryConfig(max_retries=2), **overrides})


def ok_body(text: str = "answer", model: str = "m") -> dict:
    return {"model": model, "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(openrouter.asyncio, "sleep", record)
    return delays


def run(s: Settings, handler, call):
    async def go():
        async with OpenRouterClient(s, transport=httpx.MockTransport(handler)) as client:
            return await call(client)
    return asyncio.run(go())


def complete(s: Settings, handler):
    return run(s, handler, lambda c: c.complete([{"role": "user", "content": "hi"}], model="m"))


def test_the_client_needs_the_key():
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        OpenRouterClient(Settings())


def test_complete_parses_the_response_and_sends_auth_and_sampling():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["body"] = request.headers["Authorization"], json.loads(request.content)
        return httpx.Response(200, json=ok_body("hi"))

    result = complete(settings(), handler)

    assert (result.text, result.cost_usd, result.prompt_tokens) == ("hi", 0.001, 10)
    assert seen["auth"] == "Bearer test-key" and "response_format" not in seen["body"]
    assert (seen["body"]["temperature"], seen["body"]["top_p"]) == (0.0, 1.0)


def test_retry_on_429_honours_retry_after(no_sleep):
    calls = iter([429, 429, 200])

    def handler(request):
        status = next(calls)
        return (httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "slow"}})
                if status == 429 else httpx.Response(200, json=ok_body()))

    assert complete(settings(), handler).text == "answer" and no_sleep == [2.0, 2.0]


def test_retry_uses_backoff_without_retry_after(no_sleep):
    s = settings(retry=RetryConfig(max_retries=2, base_delay_s=1, jitter=False))

    with pytest.raises(OpenRouterError, match="gave up after 3 attempts") as info:
        complete(s, lambda _: httpx.Response(503, json={"error": {"message": "down"}}))

    assert info.value.status_code == 503 and no_sleep == [1.0, 2.0]


def test_no_retry_on_a_client_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(OpenRouterError, match="bad key") as info:
        complete(settings(), handler)
    assert info.value.status_code == 401 and len(calls) == 1


def test_an_error_inside_a_200_body_is_retried_unless_fatal():
    replies = iter([{"error": {"message": "provider"}}, ok_body()])
    assert complete(settings(), lambda _: httpx.Response(200, json=next(replies))).text == "answer"
    with pytest.raises(OpenRouterError) as info:
        complete(settings(), lambda _: httpx.Response(200, json={"error": {"code": 401, "message": "no key"}}))
    assert info.value.status_code == 401


def test_a_malformed_200_response_is_retried():
    replies = iter([httpx.Response(200, content=b"<html>truncated"), httpx.Response(200, json={"choices": []}),
                    httpx.Response(200, json=ok_body())])
    assert complete(settings(), lambda _: next(replies)).text == "answer"


def test_the_attempt_timeout_is_retried_then_fails():
    s = settings(timeout=TimeoutConfig(attempt_s=0.01), retry=RetryConfig(max_retries=1, base_delay_s=0, jitter=False))

    async def slow(request):
        await REAL_SLEEP(1)
        return httpx.Response(200, json=ok_body())

    with pytest.raises(OpenRouterError, match="gave up after 2 attempts"):
        complete(s, slow)


# ---------------------------------------------------------------- /rerank


def rerank_body(scores: dict[int, float]) -> dict:   # deliberately not sorted: the client sorts itself
    return {"model": "nvidia/rerank", "results": [{"index": i, "relevance_score": s} for i, s in scores.items()],
            "usage": {"total_tokens": 42, "cost": 0.0005}}


def test_rerank_request_and_parsing():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=rerank_body({0: 0.1, 2: 0.9, 1: 0.5}))

    ranking = run(settings(), handler, lambda c: c.rerank("q", ["a", "b", "c"], model="nvidia/rerank", top_n=3))

    assert seen[0].url.path.endswith("/rerank")
    assert json.loads(seen[0].content) == {"model": "nvidia/rerank", "query": "q",
                                           "documents": [{"text": t} for t in "abc"], "top_n": 3}
    assert ranking.indices == (2, 1, 0) and ranking.scores == (0.9, 0.5, 0.1) and ranking.cost_usd == 0.0005


def test_rerank_rejects_an_out_of_range_index():
    with pytest.raises(OpenRouterError, match="out-of-range"):
        run(settings(retry=RetryConfig(max_retries=0)), lambda _: httpx.Response(200, json=rerank_body({7: 0.9})),
            lambda c: c.rerank("q", ["a"], model="nvidia/rerank", top_n=1))


def embeddings_body(vectors: dict[int, list[float]]) -> dict:   # deliberately not in index order
    return {"model": "text-embedding-3-large", "object": "list",
            "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in vectors.items()],
            "usage": {"prompt_tokens": 12, "total_tokens": 12, "cost": 0.0000016}}


def test_embed_request_and_parsing():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=embeddings_body({1: [0.0, 1.0], 0: [1.0, 0.0]}))

    result = run(settings(), handler, lambda c: c.embed(["a", "b"], model="openai/text-embedding-3-large"))

    assert seen[0].url.path.endswith("/embeddings")
    assert json.loads(seen[0].content) == {"model": "openai/text-embedding-3-large", "input": ["a", "b"],
                                           "encoding_format": "float"}
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0)) and (result.tokens, result.cost_usd) == (12, 0.0000016)


def test_an_incomplete_embeddings_response_is_an_error():
    with pytest.raises(OpenRouterError, match="embeddings for 1 of 2"):
        run(settings(retry=RetryConfig(max_retries=0)), lambda _: httpx.Response(200, json=embeddings_body({0: [1.0]})),
            lambda c: c.embed(["a", "b"], model="m"))


def test_the_openrouter_reranker_gives_every_text_a_score(monkeypatch):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=rerank_body({2: 0.9, 0: 0.4})))
    monkeypatch.setattr("hr_compass.knowledge.infrastructure.rerankers.OpenRouterClient",
                        lambda s: OpenRouterClient(s, transport=transport))

    scores = OpenRouterReranker(settings(), "nvidia/rerank").scores("q", ["a", "b", "c"])

    assert scores == [0.4, float("-inf"), 0.9]   # a text the provider did not rank goes last
    assert OpenRouterReranker(settings(), "x").scores("q", []) == []


# ---------------------------------------------------------------- logging


def _records(caplog, prefix: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith(prefix)]


def test_a_successful_call_logs_attempt_time_and_never_the_key(caplog):
    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        complete(settings(api_key="sk-or-SUPER-SECRET", retry=RetryConfig(max_retries=0)),
                 lambda _: httpx.Response(200, json=ok_body()))

    [ok] = _records(caplog, "llm call ok")
    assert "attempt=1/1" in ok.getMessage() and TIMING.search(ok.getMessage())
    assert "input_tokens=10 output_tokens=5" in ok.getMessage()
    assert "SUPER-SECRET" not in caplog.text and "Bearer" not in caplog.text


def test_failed_attempts_exhausted_retries_and_rejections_are_logged_with_timing(caplog):
    busy = httpx.Response(503, json={"error": {"message": "busy"}})
    with caplog.at_level(logging.INFO, logger="hr_compass"), pytest.raises(OpenRouterError):
        complete(settings(retry=RetryConfig(max_retries=1, base_delay_s=0)), lambda _: busy)
    assert len(_records(caplog, "llm attempt failed")) == 2
    [gave_up] = _records(caplog, "llm call failed")
    assert gave_up.levelno == logging.ERROR and re.search(r"after 2 attempts total=\d+\.\d\ds", gave_up.getMessage())

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="hr_compass"), pytest.raises(OpenRouterError):
        complete(settings(retry=RetryConfig(max_retries=3)), lambda _: httpx.Response(401, json={"error": "x"}))
    [rejected] = _records(caplog, "llm call rejected")
    assert "attempt=1/4" in rejected.getMessage() and TIMING.search(rejected.getMessage())
