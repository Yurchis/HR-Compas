from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from hr_compass import openrouter
from hr_compass.config import (
    ConfigError,
    FallbackConfig,
    GenerationConfig,
    RetryConfig,
    Settings,
    StructuredOutputConfig,
    TimeoutConfig,
)
from hr_compass.knowledge import Chunk, KnowledgeError, load_chunks, render_context
from hr_compass.openrouter import OpenRouterClient, OpenRouterError
from hr_compass.prompts import PromptError, PromptTemplate
from hr_compass.resilient import LLMError, ResilientLLM
from hr_compass.evaluate import comparison_table
from hr_compass.runner import EvaluationRunner, SampleResult, check_keywords, percentile, summarize
from hr_compass.samples import Sample, SampleError, load_samples
from hr_compass.schema import parse_answer

ROOT = Path(__file__).resolve().parent.parent
REAL_SLEEP = asyncio.sleep  # captured before the autouse fixture patches it
GOOD_JSON = json.dumps({"found": True, "answer": "3 days", "sources": ["3-12"], "confidence": "high"})


def make_settings(**overrides: object) -> Settings:
    defaults: dict = {
        "api_key": "test-key",
        "retry": RetryConfig(max_retries=2),
        "structured_output": StructuredOutputConfig(enabled=False),
        "fallback": FallbackConfig(enabled=False),
    }
    return Settings(**{**defaults, **overrides})


def ok_body(text: str = "answer", model: str = "m") -> dict:
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(openrouter.asyncio, "sleep", record)
    return delays


def run(settings: Settings, handler, coro_factory):
    async def go():
        client = OpenRouterClient(settings, transport=httpx.MockTransport(handler))
        async with client:
            return await coro_factory(client)

    return asyncio.run(go())


# --- config -----------------------------------------------------------------------------------


def test_shipped_config_loads() -> None:
    s = Settings.load(env={"OPENROUTER_API_KEY": "k"})
    assert s.model_chain[0] == s.model and len(s.model_chain) >= 2
    assert s.retry.max_retries >= 0 and s.timeout.attempt_s > 0


def test_config_requires_api_key() -> None:
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        Settings.load(env={})


def test_config_rejects_unknown_key_and_bad_value(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    env = {"OPENROUTER_API_KEY": "k"}
    f.write_text("[retry]\nbogus = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown key"):
        Settings.load(f, env)
    f.write_text("[timeout]\nconnect_s = -1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="connect_s"):
        Settings.load(f, env)
    f.write_text("[nope]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown section"):
        Settings.load(f, env)


def test_settings_repr_hides_key() -> None:
    assert "test-key" not in repr(make_settings())


def test_backoff_is_exponential_and_capped() -> None:
    r = RetryConfig(base_delay_s=1, multiplier=2, max_delay_s=5, jitter=False)
    assert [r.delay(i, 0.5) for i in range(5)] == [1, 2, 4, 5, 5]
    assert RetryConfig(base_delay_s=1, jitter=True).delay(2, 0.5) == 2.0


# --- timeout + retry --------------------------------------------------------------------------


def test_complete_parses_response_and_sends_auth() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body("hi"))

    result = run(make_settings(), handler, lambda c: c.complete([], model="m"))
    assert (result.text, result.cost_usd, result.prompt_tokens) == ("hi", 0.001, 10)
    assert seen["auth"] == "Bearer test-key"
    assert "response_format" not in seen["body"]


def test_sampling_params_come_from_config(tmp_path: Path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ok_body())

    f = tmp_path / "c.toml"
    f.write_text("[generation]\ntemperature = 0.7\ntop_p = 0.9\nmax_tokens = 256\n", encoding="utf-8")
    settings = Settings.load(f, env={"OPENROUTER_API_KEY": "k"})
    run(settings, handler, lambda c: c.complete([], model="m"))
    assert (seen["temperature"], seen["top_p"], seen["max_tokens"]) == (0.7, 0.9, 256)


@pytest.mark.parametrize("top_p", [0, 1.5])
def test_top_p_is_validated(top_p: float) -> None:
    with pytest.raises(ConfigError, match="top_p"):
        GenerationConfig(top_p=top_p)


def test_retry_on_429_honours_retry_after(no_sleep: list[float]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "slow"}})
        return httpx.Response(200, json=ok_body())

    assert run(make_settings(), handler, lambda c: c.complete([], model="m")).text == "answer"
    assert calls == 3 and no_sleep == [2.0, 2.0]


def test_retry_uses_backoff_without_retry_after(no_sleep: list[float]) -> None:
    settings = make_settings(retry=RetryConfig(max_retries=2, base_delay_s=1, jitter=False))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "down"}})

    with pytest.raises(OpenRouterError, match="gave up after 3 attempts") as info:
        run(settings, handler, lambda c: c.complete([], model="m"))
    assert info.value.status_code == 503
    assert no_sleep == [1.0, 2.0]


def test_no_retry_on_client_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(OpenRouterError, match="bad key") as info:
        run(make_settings(), handler, lambda c: c.complete([], model="m"))
    assert info.value.status_code == 401 and calls == 1


def test_retry_error_inside_200_body() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"error": {"message": "provider"}})
        return httpx.Response(200, json=ok_body())

    assert run(make_settings(), handler, lambda c: c.complete([], model="m")).text == "answer"


def test_attempt_timeout_is_retried_then_fails() -> None:
    settings = make_settings(
        timeout=TimeoutConfig(attempt_s=0.01), retry=RetryConfig(max_retries=1, base_delay_s=0, jitter=False)
    )

    async def slow(request: httpx.Request) -> httpx.Response:
        await REAL_SLEEP(1)
        return httpx.Response(200, json=ok_body())

    with pytest.raises(OpenRouterError, match="gave up after 2 attempts"):
        run(settings, slow, lambda c: c.complete([], model="m"))


# --- structured output ------------------------------------------------------------------------


def test_parse_answer_accepts_fence_and_rejects_ungrounded() -> None:
    assert parse_answer(f"```json\n{GOOD_JSON}\n```").sources == ["3-12"]
    with pytest.raises(ValueError):
        parse_answer(json.dumps({"found": True, "answer": "x", "sources": [], "confidence": "high"}))
    with pytest.raises(ValueError):
        parse_answer("not json")
    with pytest.raises(ValueError):
        parse_answer(json.dumps({"found": False, "answer": "x", "sources": [], "confidence": "sure"}))


def structured_settings(**kw: object) -> Settings:
    return make_settings(structured_output=StructuredOutputConfig(max_repair_attempts=1), **kw)


def test_structured_request_and_repair_loop() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=ok_body("oops" if len(bodies) == 1 else GOOD_JSON))

    settings = structured_settings()
    result = run(settings, handler, lambda c: ResilientLLM(c, settings).generate([{"role": "user", "content": "q"}]))
    assert result.parsed and result.parsed.answer == "3 days"
    assert bodies[0]["response_format"]["json_schema"]["strict"] is True
    assert bodies[1]["messages"][-1]["content"].startswith("Your reply failed validation")
    assert result.completion.prompt_tokens == 20  # usage summed over both attempts


def test_invalid_output_exhausts_repairs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ok_body("never json"))

    settings = structured_settings()
    with pytest.raises(LLMError, match="invalid structured output after 2 attempt"):
        run(settings, handler, lambda c: ResilientLLM(c, settings).generate([]))


# --- fallback ---------------------------------------------------------------------------------


def fallback_settings() -> Settings:
    return make_settings(
        model="primary",
        retry=RetryConfig(max_retries=0),
        fallback=FallbackConfig(enabled=True, models=("backup-1", "backup-2")),
    )


def test_fallback_to_next_model_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == "backup-2":
            return httpx.Response(200, json=ok_body("ok", model))
        return httpx.Response(503, json={"error": {"message": "down"}})

    settings = fallback_settings()
    result = run(settings, handler, lambda c: ResilientLLM(c, settings).generate([]))
    assert result.model_used == "backup-2" and result.fallback_used
    assert [f.split(":")[0] for f in result.failures] == ["primary", "backup-1"]


def test_fallback_skipped_for_auth_errors() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models.append(json.loads(request.content)["model"])
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    settings = fallback_settings()
    with pytest.raises(LLMError, match="bad key"):
        run(settings, handler, lambda c: ResilientLLM(c, settings).generate([]))
    assert models == ["primary"]


def test_all_models_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "x"}})

    settings = fallback_settings()
    with pytest.raises(LLMError) as info:
        run(settings, handler, lambda c: ResilientLLM(c, settings).generate([]))
    assert len(info.value.failures) == 3


@pytest.mark.parametrize(
    ("status", "retried", "falls_back"),
    [
        (429, True, True),  # rate limit: backoff, then next model
        (500, True, True),
        (502, True, True),
        (503, True, True),
        (400, False, False),  # our request is wrong: fix the code, another model won't help
        (401, False, False),  # bad key
        (403, False, False),  # no access
    ],
)
def test_error_matrix(status: int, retried: bool, falls_back: bool) -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models.append(json.loads(request.content)["model"])
        return httpx.Response(status, json={"error": {"message": "x"}})

    settings = make_settings(
        model="primary",
        retry=RetryConfig(max_retries=2),
        fallback=FallbackConfig(enabled=True, models=("backup",)),
    )
    with pytest.raises(LLMError):
        run(settings, handler, lambda c: ResilientLLM(c, settings).generate([]))
    per_model = 3 if retried else 1
    assert models == ["primary"] * per_model + (["backup"] * per_model if falls_back else [])


def test_error_code_inside_200_body_is_not_retried_when_fatal() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"error": {"code": 401, "message": "no key"}})

    with pytest.raises(OpenRouterError) as info:
        run(make_settings(), handler, lambda c: c.complete([], model="m"))
    assert info.value.status_code == 401 and calls == 1


def test_malformed_200_response_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, content=b"<html>truncated")
        if calls == 2:
            return httpx.Response(200, json={"choices": []})
        return httpx.Response(200, json=ok_body())

    assert run(make_settings(), handler, lambda c: c.complete([], model="m")).text == "answer"
    assert calls == 3


def test_config_rejects_overlapping_retry_and_skip_statuses() -> None:
    with pytest.raises(ConfigError, match="overlap"):
        make_settings(fallback=FallbackConfig(skip_statuses=(429,)))


def test_runner_survives_unexpected_exception() -> None:
    class Boom:
        async def generate(self, messages: list, **kwargs: object) -> None:
            raise KeyError("bug")

    prompt = PromptTemplate(name="t", template="{{context}}")
    chunks = [Chunk("1-1", "A", "S", "USA", ("IT-Product",), ("all",), "paid", None, "ta")]
    results = asyncio.run(EvaluationRunner(Boom(), prompt, chunks, concurrency=1).run([Sample("s1", "q")]))  # type: ignore[arg-type]
    assert results[0].error and "bug" in results[0].error


def test_fallback_disabled_uses_primary_only() -> None:
    s = make_settings(fallback=FallbackConfig(enabled=False, models=("x",)))
    assert s.model_chain == (s.model,)


# --- data loaders -----------------------------------------------------------------------------


def test_prompt_requires_placeholder(tmp_path: Path) -> None:
    f = tmp_path / "p.md"
    f.write_text("no placeholder", encoding="utf-8")
    with pytest.raises(PromptError):
        PromptTemplate.from_file(f)


def test_prompt_render_keeps_braces(tmp_path: Path) -> None:
    f = tmp_path / "v9.md"
    f.write_text("{json} {{context}}", encoding="utf-8")
    prompt = PromptTemplate.from_file(f)
    assert prompt.name == "v9" and prompt.render(context="{x}") == "{json} {x}"


def test_load_samples_validates(tmp_path: Path) -> None:
    f = tmp_path / "s.jsonl"
    f.write_text('# c\n{"id": "a", "question": "q"}\n{"id": "a", "question": "q2"}\n', encoding="utf-8")
    with pytest.raises(SampleError, match="duplicate"):
        load_samples(f)
    f.write_text('{"id": "a"}\n', encoding="utf-8")
    with pytest.raises(SampleError, match=":1:"):
        load_samples(f)


def test_bundled_data_is_loadable() -> None:
    assert len(load_chunks(ROOT / "data" / "raw")) > 50
    assert len(load_samples(ROOT / "data" / "golden_set.jsonl")) >= 1
    for name in ("v1_baseline.md", "v2_structured.md", "v3_country_clarification.md"):
        PromptTemplate.from_file(ROOT / "prompts" / name)


def test_render_context_filters() -> None:
    chunks = [
        Chunk("1-1", "A", "S", "USA", ("IT-Product",), ("all",), "paid", None, "ta"),
        Chunk("1-2", "B", "S", "UA", ("IT-Outsourcing",), ("all",), "paid", "who", "tb"),
    ]
    ctx = render_context(chunks, country="UA")
    assert "[1-2]" in ctx and "[1-1]" not in ctx and "eligibility: who" in ctx
    with pytest.raises(KnowledgeError):
        render_context(chunks, country="Costa Rica")


def test_percentile_nearest_rank() -> None:
    values = [float(i) for i in range(1, 11)]  # 1..10
    assert (percentile(values, 50), percentile(values, 95), percentile(values, 0)) == (5.0, 10.0, 1.0)
    assert percentile([2.5], 95) == 2.5
    assert percentile([], 50) is None


def test_summary_and_table_report_p50_p95_over_successes_only() -> None:
    def result(i: int, latency: float, error: str | None = None) -> SampleResult:
        return SampleResult(f"s{i}", "q", None if error else "a", None, None, error, latency)

    results = [result(i, float(i)) for i in range(1, 5)] + [result(9, 99.0, error="boom")]
    s = summarize(results)
    assert (s["latency_p50_s"], s["latency_p95_s"]) == (2.0, 4.0)  # the failed 99s sample is excluded
    table = comparison_table([{"model": "m", "summary": s}])
    assert "| p50, с | p95, с |" in table and "| 2.0 | 4.0 | 4/5 |" in table


def test_failed_sample_counts_as_wrong_in_accuracy() -> None:
    def result(i: int, passed: bool | None, error: str | None = None) -> SampleResult:
        return SampleResult(f"s{i}", "q", None if error else "a", None, passed, error, 1.0)

    s = summarize([result(1, True), result(2, True), result(3, False), result(4, False, error="boom"), result(5, None)])
    assert (s["keyword_passed"], s["keyword_checked"], s["accuracy_pct"]) == (2, 4, 50.0)


def test_comparison_table_has_report_columns() -> None:
    s = summarize([SampleResult("s1", "q", "a", None, True, None, 1.5, prompt_tokens=265540, completion_tokens=812)])
    row = {
        "model": "openai/gpt-4o-mini",
        "prompt": "v2_structured",
        "generation": {"temperature": 0.0, "top_p": 1.0, "max_tokens": 1024},
        "price": (0.15, 0.6),
        "summary": s,
    }
    header, _, line = comparison_table([row]).splitlines()
    assert header.startswith(
        "| Модель | Версія промпту | Семплінг | Ціна, $/1M (вх/вих) | Правильні, % | Тип відповіді, % |"
    )
    assert line.startswith(
        "| openai/gpt-4o-mini | v2_structured | temperature=0.0, top_p=1.0 | 0.15 / 0.6 | 100.0% (1/1) | — "
        "| 265 540 | 812 |"
    )
    with_intake = comparison_table([{**row, "intake": "intake_v2_en"}])
    assert "| v2_structured + intake_v2_en |" in with_intake
    assert "| — |" in comparison_table([{**row, "price": None, "rerank": "r"}])  # unknown price
    assert "openai/gpt-4o-mini + rerank" in comparison_table([{**row, "rerank": "r"}])


def test_pricing_is_loaded_and_validated(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    f.write_text('[pricing]\n"a/b" = [0.15, 0.60]\n', encoding="utf-8")
    assert Settings.load(f, env={"OPENROUTER_API_KEY": "k"}).pricing == {"a/b": (0.15, 0.6)}
    f.write_text('[pricing]\n"a/b" = [-1, 0.6]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="pricing"):
        Settings.load(f, env={"OPENROUTER_API_KEY": "k"})


def test_latency_excludes_waiting_for_a_concurrency_slot() -> None:
    class SlowLLM:
        async def generate(self, messages, **kwargs):
            await asyncio.sleep(0.05)
            from tests.test_chat import completion
            from hr_compass.resilient import LLMResult

            return LLMResult(completion("x"), None, "m")

    chunks = [Chunk("1-1", "A", "S", "USA", ("IT-Product",), ("all",), "paid", None, "ta")]
    runner = EvaluationRunner(SlowLLM(), PromptTemplate("t", "{{context}}"), chunks, concurrency=1)  # type: ignore[arg-type]
    results = asyncio.run(runner.run([Sample(f"s{i}", "q") for i in range(4)]))
    # Run serially, the 4th sample waits ~0.15s for the slot; its own call still takes ~0.05s.
    assert max(r.latency_s for r in results) < 0.12


def test_check_keywords() -> None:
    assert check_keywords("Up to 3 DAYS", ["3", "days"]) is True
    assert check_keywords("none", ["3"]) is False
    assert check_keywords("x", []) is None


# --- runner -----------------------------------------------------------------------------------


def test_runner_isolates_failures_and_keeps_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        question = json.loads(request.content)["messages"][-1]["content"]
        if question == "bad":
            return httpx.Response(400, json={"error": {"message": "nope"}})
        return httpx.Response(200, json=ok_body(GOOD_JSON))

    chunks = [Chunk("1-1", "A", "S", "USA", ("IT-Product",), ("all",), "paid", None, "ta")]
    prompt = PromptTemplate(name="t", template="ctx: {{context}}")
    samples = [Sample("s1", "good", expected_keywords=("3",)), Sample("s2", "bad"), Sample("s3", "good")]
    settings = structured_settings()

    results = run(
        settings,
        handler,
        lambda c: EvaluationRunner(ResilientLLM(c, settings), prompt, chunks, concurrency=2).run(samples),
    )
    assert [r.id for r in results] == ["s1", "s2", "s3"]
    assert results[0].keywords_passed is True and results[0].sources == ("3-12",)
    assert results[1].error and results[1].answer is None
    summary = summarize(results)
    assert (summary["succeeded"], summary["failed"], summary["keyword_passed"]) == (2, 1, 1)
    assert summary["cost_usd"] == pytest.approx(0.002)
