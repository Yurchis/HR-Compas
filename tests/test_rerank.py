from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from hr_compass.config import ConfigError, RerankConfig, RetryConfig, Settings
from hr_compass.knowledge import Chunk
from hr_compass.openrouter import OpenRouterError
from hr_compass.pipeline import HRCompass
from hr_compass.prompts import PromptTemplate
from hr_compass.resilient import ResilientLLM
from hr_compass.retrieval import Reranker
from hr_compass.runner import EvaluationRunner, summarize
from hr_compass.samples import Sample
from tests.test_chat import FakeLLM, chunk
from tests.test_evaluation import GOOD_JSON, make_settings, ok_body, run, structured_settings

ROOT = Path(__file__).resolve().parent.parent
CHUNKS = [chunk(f"1-{i}") for i in range(1, 6)]


def rerank_body(scores: dict[int, float], cost: float = 0.0005) -> dict:
    # Deliberately not sorted by score: the client must sort itself.
    return {
        "model": "nvidia/rerank",
        "results": [{"index": i, "relevance_score": s} for i, s in scores.items()],
        "usage": {"total_tokens": 42, "cost": cost},
    }


def rerank_settings(top_n: int = 2, **kw: object) -> Settings:
    return make_settings(rerank=RerankConfig(enabled=True, model="nvidia/rerank", top_n=top_n), **kw)


def select(settings: Settings, handler, chunks: list[Chunk] = CHUNKS):
    return run(settings, handler, lambda c: Reranker(c, settings.rerank).select("vacation?", chunks))


# --- config -----------------------------------------------------------------------------------


def test_shipped_config_has_rerank_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.load(ROOT / "config" / "settings.toml", env={"OPENROUTER_API_KEY": "k"})
    assert settings.rerank.enabled is False
    assert settings.rerank.model == "nvidia/llama-nemotron-rerank-vl-1b-v2:free" and settings.rerank.top_n >= 1


def test_rerank_config_validation(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="top_n"):
        RerankConfig(top_n=0)
    path = tmp_path / "s.toml"
    path.write_text('[rerank]\nenabled = true\nbogus = 1\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="bogus"):
        Settings.load(path, env={"OPENROUTER_API_KEY": "k"})


# --- client -----------------------------------------------------------------------------------


def test_client_rerank_request_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=rerank_body({0: 0.1, 2: 0.9, 1: 0.5}))

    settings = rerank_settings()
    ranking = run(settings, handler, lambda c: c.rerank("q", ["a", "b", "c"], model="nvidia/rerank", top_n=3))
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/rerank")
    assert body == {"model": "nvidia/rerank", "query": "q", "documents": [{"text": t} for t in "abc"], "top_n": 3}
    assert ranking.indices == (2, 1, 0) and ranking.scores == (0.9, 0.5, 0.1)
    assert (ranking.tokens, ranking.cost_usd) == (42, 0.0005)


def test_client_rerank_rejects_out_of_range_index() -> None:
    settings = rerank_settings(retry=RetryConfig(max_retries=0))
    handler = lambda _: httpx.Response(200, json=rerank_body({7: 0.9}))  # noqa: E731
    with pytest.raises(OpenRouterError, match="out-of-range"):
        run(settings, handler, lambda c: c.rerank("q", ["a"], model="nvidia/rerank", top_n=1))


# --- reranker ---------------------------------------------------------------------------------


def test_reranker_keeps_top_n_in_score_order() -> None:
    selection = select(rerank_settings(top_n=2), lambda _: httpx.Response(200, json=rerank_body({0: 0.1, 3: 0.8, 4: 0.6})))
    assert [c.id for c in selection.chunks] == ["1-4", "1-5"]
    assert selection.reranked and selection.cost_usd == pytest.approx(0.0005)


def test_reranker_skips_the_call_when_chunks_fit_top_n() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("rerank must not be called")

    selection = select(rerank_settings(top_n=5), handler)
    assert selection.chunks == CHUNKS and not selection.reranked


def test_reranker_failure_falls_back_to_full_context(caplog: pytest.LogCaptureFixture) -> None:
    settings = rerank_settings(retry=RetryConfig(max_retries=0))
    with caplog.at_level("WARNING", logger="hr_compass"):
        selection = select(settings, lambda _: httpx.Response(401, json={"error": {"message": "bad key"}}))
    assert selection.chunks == CHUNKS and not selection.reranked and selection.cost_usd == 0
    assert "rerank failed after" in caplog.text and "using full context" in caplog.text


# --- pipeline / runner ------------------------------------------------------------------------


class FixedReranker:
    """Stands in for Reranker: always picks the given chunk ids."""

    def __init__(self, ids: list[str], cost: float = 0.0005) -> None:
        self.ids, self.cost, self.questions = ids, cost, []

    async def select(self, question, chunks):
        from hr_compass.retrieval import Selection

        self.questions.append(question)
        return Selection([c for c in chunks if c.id in self.ids], cost_usd=self.cost, reranked=True)


def test_pipeline_puts_only_reranked_chunks_into_the_prompt() -> None:
    llm, reranker = FakeLLM(), FixedReranker(["1-2"])
    prompt = PromptTemplate("p", "RULES\n{{context}}")
    bot = HRCompass(llm, prompt, CHUNKS, intake_prompt=None, reranker=reranker)  # type: ignore[arg-type]
    reply = asyncio.run(bot.ask("vacation?"))
    system = llm.calls[-1][1][0]["content"]
    assert "[1-2]" in system and "[1-1]" not in system and "[1-3]" not in system
    assert reranker.questions == ["vacation?"]
    assert reply.cost_usd == pytest.approx(0.001 + 0.0005)  # answer call + rerank


def test_runner_reranks_records_chunks_and_adds_cost(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rerank"):
            return httpx.Response(200, json=rerank_body({1: 0.9, 0: 0.2}))
        system = json.loads(request.content)["messages"][0]["content"]
        assert "[1-2]" in system and "[1-3]" not in system
        return httpx.Response(200, json=ok_body(GOOD_JSON))

    settings = structured_settings(rerank=RerankConfig(enabled=True, model="nvidia/rerank", top_n=1))
    prompt = PromptTemplate(name="t", template="ctx: {{context}}")

    def go(c):
        runner = EvaluationRunner(
            ResilientLLM(c, settings), prompt, CHUNKS, concurrency=1, reranker=Reranker(c, settings.rerank)
        )
        return runner.run([Sample("s1", "q")])

    with caplog.at_level("INFO", logger="hr_compass"):
        [result] = run(settings, handler, go)
    assert "rerank call ok model=nvidia/rerank" in caplog.text and "input_tokens=42" in caplog.text
    assert "s1: ok via openai/gpt-4o-mini input_tokens=10 output_tokens=5" in caplog.text
    assert result.error is None and result.retrieved == ("1-2",)
    assert result.cost_usd == pytest.approx(0.001 + 0.0005)
    assert summarize([result])["cost_usd"] == pytest.approx(0.0015)
