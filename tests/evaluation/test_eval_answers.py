"""The answer eval: the bot on every case, scores, judge, summary, comparison table and report."""

from __future__ import annotations

import asyncio
import json

import pytest

from hr_compass.assistant.domain.reply import Reply
from hr_compass.evaluation.application.eval_answers import (
    Outcome,
    answer_cases,
    comparison_table,
    judge_outcomes,
    percentile,
    report_markdown,
    score_outcomes,
    summarize,
)
from hr_compass.evaluation.application.judges import LlmJudge
from hr_compass.shared.llm import LLMError
from tests.fakes import FakeChat

CASES = [
    {"id": "q01", "kind": "paraphrase", "groups": ["all_employees"], "question": "remote days?",
     "relevant": ["h#105"], "must": [["one day"]], "reference": "One day a week."},
    {"id": "q02", "kind": "paraphrase", "groups": ["all_employees", "hr"], "question": "broken?",
     "relevant": ["h#1"], "must": [["x"]], "reference": "X."},
    {"id": "q24", "kind": "no_answer", "groups": ["all_employees"], "question": "gym?", "reference": "Not in docs."},
]


class FakeBot:
    """The Asker port: answers q01, fails q02, abstains on q24; records the calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ask(self, question, *, groups, country=None, history=(), allow_clarification=True, rid=None):
        self.calls.append({"rid": rid, "groups": list(groups), "allow_clarification": allow_clarification})
        await asyncio.sleep(0.01 if rid == "q01" else 0)   # finishes last: order must still hold
        if rid == "q02":
            raise LLMError(["m: down"])
        if rid == "q24":
            return Reply("answer", "I could not find this.", found=False, cost_usd=0.001)
        return Reply("answer", "One day a week.", found=True, cited=("h#105",), sources={"h#105": "one day per week"},
                     prompt_tokens=100, completion_tokens=10, cost_usd=0.002)


@pytest.fixture
def outcomes() -> list[Outcome]:
    bot = FakeBot()
    result = asyncio.run(answer_cases(bot, CASES, concurrency=2))
    assert all(c["allow_clarification"] is False for c in bot.calls)   # an eval wants answers, not questions back
    return result


def test_results_keep_the_testset_order_and_a_failing_case_never_stops_the_run(outcomes):
    assert [o.case_id for o in outcomes] == ["q01", "q02", "q24"]
    assert outcomes[1].reply is None and "down" in outcomes[1].error
    assert outcomes[1].result() == {"found": False, "answer": "", "cited": []}   # scored as a failed answer


def test_scores_and_summary(outcomes):
    scores = score_outcomes(CASES, outcomes)

    m = summarize(CASES, outcomes, scores)

    assert [s["pass"] for s in scores] == [True, False, True]
    assert m["pass"] == pytest.approx(2 / 3) and m["failed"] == ["q02"] and m["errors"] == ["q02"]
    assert m["cost_usd"] == pytest.approx(0.003) and m["input_tokens"] == 100
    assert m["latency_p50_s"] is not None   # over the successful cases only


def test_the_judge_adds_correctness_and_groundedness(outcomes):
    llm = FakeChat([json.dumps({"reason": "same", "verdict": "correct"}),
                    json.dumps({"claims": [{"claim": "one day", "supported": True}]}),
                    json.dumps({"reason": "no answer", "verdict": "incorrect"}),
                    json.dumps({"reason": "abstained", "verdict": "correct"})])
    scores = score_outcomes(CASES, outcomes)

    judge_outcomes(LlmJudge(llm, "correct?", "grounded?"), CASES, outcomes, scores)

    assert [s["judge"] for s in scores] == [True, False, True]
    assert [s["grounded"] for s in scores] == [True, None, None]   # not-found answers: no groundedness call
    assert "one day per week" in llm.asked[1]["messages"][1]["content"]   # the cited source text


def test_percentile_nearest_rank():
    values = [float(i) for i in range(1, 11)]
    assert (percentile(values, 50), percentile(values, 95), percentile(values, 0)) == (5.0, 10.0, 1.0)
    assert percentile([2.5], 95) == 2.5 and percentile([], 50) is None


def test_comparison_table_and_report(outcomes):
    scores = score_outcomes(CASES, outcomes)
    metrics = summarize(CASES, outcomes, scores)

    table = comparison_table({"openai/gpt-4o-mini": metrics})
    report = report_markdown("openai/gpt-4o-mini", "v5_rag", metrics, CASES, outcomes, scores)

    header, _, row = table.splitlines()
    assert header.startswith("| Model | pass | facts | cited |") and row.startswith("| openai/gpt-4o-mini | 0.67 |")
    assert "### q02 (paraphrase): broken?" in report and "### q01" not in report   # only cases worth reading
    assert "| pass | 0.67 |" in report
