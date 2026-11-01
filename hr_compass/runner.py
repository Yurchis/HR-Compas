"""Run samples through the bot pipeline (intake -> context -> answer) concurrently and collect per-sample results."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from hr_compass.knowledge import Chunk
from hr_compass.logging_setup import request_id
from hr_compass.pipeline import HRCompass
from hr_compass.prompts import PromptTemplate
from hr_compass.resilient import LLMError, ResilientLLM
from hr_compass.retrieval import Reranker
from hr_compass.samples import Sample

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SampleResult:
    id: str
    question: str
    answer: str | None
    expected_answer: str | None
    keywords_passed: bool | None  # None when the sample defines no keywords; False when the call failed
    error: str | None
    latency_s: float
    model_used: str | None = None
    fallback_failures: tuple[str, ...] = ()
    found: bool | None = None  # structured fields; None when structured output is off
    sources: tuple[str, ...] | None = None
    confidence: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None  # includes the intake and rerank calls
    finish_reason: str | None = None
    retrieved: tuple[str, ...] | None = None  # chunk ids picked by the reranker; None = full context
    kind: str | None = None  # reply kind: answer / clarification / out_of_scope; None when the call failed
    expected_kind: str | None = None
    kind_passed: bool | None = None  # None when the sample has no expected_kind; False when the call failed


def check_keywords(answer: str, keywords: Sequence[str]) -> bool | None:
    """True if every keyword occurs in the answer (case-insensitive); None if no keywords given."""
    if not keywords:
        return None
    lowered = answer.casefold()
    return all(k.casefold() in lowered for k in keywords)


class EvaluationRunner:
    """Asks every sample the way the chat does: the same `HRCompass` pipeline, with the sample's profile as known.

    `intake_prompt=None` skips intake: the answer model is called directly and every reply is an "answer".
    """

    def __init__(
        self,
        llm: ResilientLLM,
        prompt: PromptTemplate,
        chunks: list[Chunk],
        *,
        concurrency: int,
        reranker: Reranker | None = None,
        intake_prompt: str | None = None,
    ) -> None:
        self._bot = HRCompass(llm, prompt, chunks, intake_prompt=intake_prompt, reranker=reranker)
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self, samples: Sequence[Sample]) -> list[SampleResult]:
        """Evaluate all samples; results keep input order. A failed sample never aborts the run."""
        total = len(samples)
        done = 0

        async def one(sample: Sample) -> SampleResult:
            nonlocal done
            result = await self._run_one(sample)
            done += 1
            if result.error:
                status = f"ERROR {result.error}"
            else:
                status = (
                    f"ok via {result.model_used or '-'} "
                    f"input_tokens={result.prompt_tokens} output_tokens={result.completion_tokens} kind={result.kind}"
                )
            logger.info("[%d/%d] %s: %s (%.1fs)", done, total, sample.id, status, result.latency_s)
            return result

        return list(await asyncio.gather(*(one(s) for s in samples)))

    async def _run_one(self, sample: Sample) -> SampleResult:
        request_id.set(sample.id)  # each sample runs in its own task, so this stays local to it
        started = time.perf_counter()
        try:
            async with self._semaphore:
                # Latency is our request (intake + rerank + answer), not the wait for a free concurrency slot.
                started = time.perf_counter()
                reply = await self._bot.ask(
                    sample.question, country=sample.country, sub_company=sample.sub_company, rid=sample.id
                )
        except Exception as exc:  # noqa: BLE001 - one bad sample must never abort the whole run
            if not isinstance(exc, (LLMError, ValueError)):  # expected failures need no traceback
                logger.exception("unexpected error on sample %s", sample.id)
            return SampleResult(
                id=sample.id,
                question=sample.question,
                answer=None,
                expected_answer=sample.expected_answer,
                keywords_passed=False if sample.expected_keywords else None,  # no answer = not correct
                error=str(exc),
                latency_s=time.perf_counter() - started,
                expected_kind=sample.expected_kind,
                kind_passed=False if sample.expected_kind else None,
            )
        answered = reply.kind == "answer"
        return SampleResult(
            id=sample.id,
            question=sample.question,
            answer=reply.text,
            expected_answer=sample.expected_answer,
            keywords_passed=check_keywords(reply.text, sample.expected_keywords),
            error=None,
            latency_s=time.perf_counter() - started,
            model_used=reply.model_used,
            fallback_failures=reply.fallback_failures,
            found=reply.found,
            sources=reply.sources if answered and reply.found is not None else None,
            confidence=reply.confidence,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            cost_usd=reply.cost_usd,
            finish_reason=reply.finish_reason,
            retrieved=reply.retrieved,
            kind=reply.kind,
            expected_kind=sample.expected_kind,
            kind_passed=(reply.kind == sample.expected_kind) if sample.expected_kind else None,
        )


def percentile(sorted_values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (an observed value, no interpolation); None for an empty sample.

    On small samples high percentiles are the slowest calls: with 10 samples p95 is the maximum.
    """
    if not sorted_values:
        return None
    rank = math.ceil(q / 100 * len(sorted_values))
    return round(sorted_values[max(rank, 1) - 1], 3)


def summarize(results: Sequence[SampleResult]) -> dict[str, Any]:
    """Aggregate run-level statistics."""
    ok = [r for r in results if r.error is None]
    # Failed samples stay in the denominator: a model that fails 3 of 50 calls is wrong on those 3 in production too.
    checked = [r for r in results if r.keywords_passed is not None]
    passed = sum(1 for r in checked if r.keywords_passed)
    kind_checked = [r for r in results if r.kind_passed is not None]
    kind_passed = sum(1 for r in kind_checked if r.kind_passed)
    kinds: dict[str, int] = {}
    for r in ok:
        kinds[r.kind or "?"] = kinds.get(r.kind or "?", 0) + 1
    latencies = sorted(r.latency_s for r in ok)
    by_model: dict[str, int] = {}
    for r in ok:
        by_model[r.model_used or "?"] = by_model.get(r.model_used or "?", 0) + 1
    return {
        "total": len(results),
        "succeeded": len(ok),
        "failed": len(results) - len(ok),
        "fallback_used": sum(1 for r in ok if r.fallback_failures),
        "answered_by": by_model,
        "keyword_checked": len(checked),
        "keyword_passed": passed,
        "accuracy_pct": round(100 * passed / len(checked), 1) if checked else None,
        "kinds": kinds,  # reply kinds of the successful samples
        "kind_checked": len(kind_checked),
        "kind_passed": kind_passed,
        "kind_accuracy_pct": round(100 * kind_passed / len(kind_checked), 1) if kind_checked else None,
        "latency_mean_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "prompt_tokens": sum(r.prompt_tokens or 0 for r in ok),
        "completion_tokens": sum(r.completion_tokens or 0 for r in ok),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in ok), 6),
    }


def result_to_dict(result: SampleResult) -> dict[str, Any]:
    return asdict(result)
