"""Answer eval: the real bot (AskQuestion) on every testset case, deterministic scores, optionally the LLM judge,
run metrics, stability over repeats, a comparison table across models and a report for people."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from hr_compass.assistant.domain.reply import Reply
from hr_compass.evaluation.application.judges import LlmJudge
from hr_compass.evaluation.domain.scores import aggregate, score
from hr_compass.evaluation.domain.testset import EvalCase
from hr_compass.shared.llm import LLMError
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


class Asker(Protocol):
    async def ask(self, question: str, *, groups: Sequence[str], country: str | None = None,
                  history: Sequence[tuple[str, str]] = (), allow_clarification: bool = True,
                  rid: str | None = None) -> Reply: ...


@dataclass(frozen=True, slots=True)
class Outcome:
    """One case through the bot: the reply, or the error that stopped it (scored as a failed answer)."""

    case_id: str
    reply: Reply | None
    error: str | None
    latency_s: float

    def result(self) -> dict[str, Any]:
        return self.reply.as_result() if self.reply else {"found": False, "answer": "", "cited": []}


async def answer_cases(bot: Asker, cases: list[EvalCase], concurrency: int) -> list[Outcome]:
    """Every case through the bot, `concurrency` at a time; results keep the testset order and one failing case
    never stops the run. Latency is the bot's own time, not the wait for a free slot."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: EvalCase) -> Outcome:
        async with semaphore:
            started = time.perf_counter()
            try:
                reply = await bot.ask(case["question"], groups=case["groups"],
                                      history=[tuple(turn) for turn in case.get("history", [])],
                                      allow_clarification=False, rid=case["id"])
            except (LLMError, ValueError) as exc:
                logger.warning("case failed", extra=kv(case=case["id"], error=type(exc).__name__))
                return Outcome(case["id"], None, str(exc), time.perf_counter() - started)
            return Outcome(case["id"], reply, None, time.perf_counter() - started)

    return list(await asyncio.gather(*(one(c) for c in cases)))


def score_outcomes(cases: list[EvalCase], outcomes: list[Outcome]) -> list[dict[str, Any]]:
    return [score(o.result(), c) for o, c in zip(outcomes, cases, strict=True)]


def judge_outcomes(judge: LlmJudge, cases: list[EvalCase], outcomes: list[Outcome], scores: list[dict]) -> None:
    """Adds judge (correct vs the reference) and grounded (claims vs the cited sources) to every score."""
    for case, outcome, s in zip(cases, outcomes, scores, strict=True):
        result = outcome.result()
        verdict = judge.correct(case, result["answer"])
        s["judge"], s["judge_reason"] = verdict.verdict == "correct", verdict.reason
        sources = list(outcome.reply.sources.values()) if outcome.reply else []
        s["grounded"], s["unsupported"] = judge.grounded(result["answer"], result["found"], sources)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, -(-len(ordered) * q // 100))   # ceil
    return ordered[int(rank) - 1]


def summarize(cases: list[EvalCase], outcomes: list[Outcome], scores: list[dict]) -> dict[str, Any]:
    """aggregate() of the scores plus what the run cost: tokens, $, latency p50/p95 (successful cases), errors."""
    metrics = aggregate(scores, cases, [o.result() for o in outcomes])
    replies = [o.reply for o in outcomes if o.reply]
    latencies = [o.latency_s for o in outcomes if o.reply]
    metrics.update(
        errors=[o.case_id for o in outcomes if o.error], cost_usd=sum(r.cost_usd for r in replies),
        input_tokens=sum(r.prompt_tokens for r in replies), output_tokens=sum(r.completion_tokens for r in replies),
        latency_p50_s=percentile(latencies, 50), latency_p95_s=percentile(latencies, 95))
    return metrics


def comparison_table(rows: Mapping[str, Mapping[str, Any]]) -> str:
    """One markdown row per model: the numbers REPORT.md compares."""
    def f(value: Any) -> str:
        return "-" if value is None else f"{value:.2f}"

    lines = ["| Model | pass | facts | cited | attributed | abstain | false abstain | judge | grounded "
             "| input tokens | output tokens | $ / run | p50, s | p95, s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for model, m in rows.items():
        lines.append(f"| {model} | {f(m['pass'])} | {f(m['facts'])} | {f(m['cited'])} | {f(m.get('attributed'))} "
                     f"| {f(m['abstain'])} | {f(m['false_abstain'])} | {f(m.get('judge'))} | {f(m.get('grounded'))} "
                     f"| {m.get('input_tokens', 0)} | {m.get('output_tokens', 0)} "
                     f"| {m['cost_usd']:.4f} | {f(m['latency_p50_s'])} | {f(m['latency_p95_s'])} |")
    return "\n".join(lines)


def report_markdown(model: str, prompt: str, metrics: Mapping[str, Any], cases: list[EvalCase],
                    outcomes: list[Outcome], scores: list[dict]) -> str:
    """For people: the numbers, then every case worth reading (failed, judged incorrect or not grounded)."""
    def f(value: Any) -> str:
        return "-" if value is None else f"{value:.2f}"

    lines = [f"# Answer eval: {model}, prompt {prompt}", "", f"{len(cases)} cases, ${metrics['cost_usd']:.4f}.", "",
             "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {f(metrics.get(k))} |" for k in ("pass", "facts", "cited", "attributed", "abstain",
                                                         "false_abstain", "judge", "grounded", "pass_at_1", "pass_all")
              if metrics.get(k) is not None]
    if metrics.get("flaky") is not None:
        lines += ["", f"Flaky cases: {', '.join(metrics['flaky']) or 'none'}"]
    lines += ["", "## By kind", "", "| kind | pass |", "|---|---|"]
    lines += [f"| {k} | {f(v)} |" for k, v in metrics["by_kind"].items()]
    lines += ["", "## Cases to read", ""]
    for case, outcome, s in zip(cases, outcomes, scores, strict=True):
        if s["pass"] and s.get("judge") is not False and s.get("grounded") is not False:
            continue
        result = outcome.result()
        lines += [f"### {case['id']} ({case['kind']}): {case['question']}", "",
                  f"- answer: {result['answer'] or outcome.error}", f"- reference: {case['reference']}",
                  f"- deterministic: facts {s['facts']}, cited {s['cited']}, abstain {s['abstain']}"]
        if "judge" in s:
            lines.append(f"- judge: {'correct' if s['judge'] else 'incorrect'}. {s['judge_reason']}")
        if s.get("unsupported"):
            lines.append(f"- not in the cited sources: {'; '.join(s['unsupported'])}")
        lines.append("")
    return "\n".join(lines)
