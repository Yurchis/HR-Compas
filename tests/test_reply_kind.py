"""Evaluation through the full pipeline: known profile, reply kind (answer / clarification / out_of_scope)."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pytest

from hr_compass.config import StructuredOutputConfig
from hr_compass.evaluate import resolve_intake
from hr_compass.intake import Intake
from hr_compass.pipeline import HRCompass
from hr_compass.prompts import PromptTemplate
from hr_compass.resilient import LLMError, LLMResult
from hr_compass.runner import EvaluationRunner, summarize
from hr_compass.samples import Sample, SampleError, load_samples
from hr_compass.schema import HRAnswer
from tests.test_chat import ANSWER_OK, INTAKE_OK, FakeLLM, chunk, completion
from tests.test_evaluation import make_settings

ROOT = Path(__file__).resolve().parent.parent
PROMPT = PromptTemplate("p", "RULES\n{{context}}")
CHUNKS = [chunk("3-2", "USA"), chunk("3-2", "UA"), chunk("3-2", "Costa Rica")]


class ScriptedLLM(FakeLLM):
    """Intake verdict per question text; questions starting with 'fail' break the answer call."""

    def __init__(self, intakes: dict[str, dict]) -> None:
        super().__init__()
        self.intakes = intakes

    async def generate(self, messages, *, output_model=HRAnswer) -> LLMResult:
        question = messages[-1]["content"]
        self.calls.append((output_model, messages))
        if output_model is Intake:
            return LLMResult(completion(), Intake(**self.intakes.get(question, INTAKE_OK)), "fake/model")
        if question.startswith("fail"):
            raise LLMError(["fake/model: down"])
        return LLMResult(completion(), HRAnswer(**ANSWER_OK), "fake/model")


def answer_context(llm: FakeLLM) -> str:
    return next(m for kind, m in llm.calls if kind is HRAnswer)[0]["content"]


# --- samples ---------------------------------------------------------------------------------------


def test_expected_kind_is_loaded_and_validated(tmp_path: Path) -> None:
    f = tmp_path / "s.jsonl"
    f.write_text('{"id": "a", "question": "q", "expected_kind": "clarification"}\n{"id": "b", "question": "q"}\n',
                 encoding="utf-8")
    assert [s.expected_kind for s in load_samples(f)] == ["clarification", None]
    f.write_text('{"id": "a", "question": "q", "expected_kind": "maybe"}\n', encoding="utf-8")
    with pytest.raises(SampleError, match="expected_kind"):
        load_samples(f)


def test_shipped_golden_set_expects_a_clarification_only_without_a_country() -> None:
    samples = load_samples(ROOT / "data" / "golden_set.jsonl")
    assert {s.expected_kind for s in samples} == {"answer", "clarification"}
    assert all((s.expected_kind == "clarification") == (s.country is None) for s in samples)
    assert all(not s.expected_keywords for s in samples if s.expected_kind == "clarification")


# --- pipeline: known profile -----------------------------------------------------------------------


def test_known_profile_selects_the_country_handbook() -> None:
    llm = FakeLLM()  # intake finds no country in the question
    bot = HRCompass(llm, PROMPT, CHUNKS, intake_prompt="intake")
    asyncio.run(bot.ask("vacation?", country="Costa Rica", sub_company="IT-Product"))
    ctx = answer_context(llm)
    assert "country: Costa Rica" in ctx and "country: UA" not in ctx and "country: USA" not in ctx


def test_country_named_in_the_question_beats_the_profile() -> None:
    llm = FakeLLM(intake={**INTAKE_OK, "country": "UA"})
    bot = HRCompass(llm, PROMPT, CHUNKS, intake_prompt="intake")
    asyncio.run(bot.ask("vacation in Ukraine?", country="Costa Rica"))
    assert "country: UA" in answer_context(llm) and "country: Costa Rica" not in answer_context(llm)


def test_intake_is_told_the_known_profile_so_it_does_not_ask_for_it() -> None:
    llm = FakeLLM()
    bot = HRCompass(llm, PROMPT, CHUNKS, intake_prompt="intake")
    asyncio.run(bot.ask("vacation?", country="UA", sub_company="IT-Product"))
    asyncio.run(bot.ask("vacation?"))
    with_profile, without = [m for kind, m in llm.calls if kind is Intake]
    assert [m["role"] for m in with_profile] == ["system", "system", "user"]
    assert "country=UA, sub_company=IT-Product" in with_profile[1]["content"]
    assert [m["role"] for m in without] == ["system", "user"]  # nothing known: intake sees only the question


def test_without_intake_the_profile_is_still_used() -> None:
    llm = FakeLLM()
    asyncio.run(HRCompass(llm, PROMPT, CHUNKS, intake_prompt=None).ask("q", country="USA"))
    assert "country: USA" in answer_context(llm) and "country: UA" not in answer_context(llm)


# --- runner: reply kind ----------------------------------------------------------------------------


def test_runner_checks_the_reply_kind_and_counts_failures_as_wrong() -> None:
    clarify = {**INTAKE_OK, "needs_clarification": True, "clarifying_question": "Яка країна?"}
    llm = ScriptedLLM({"no country": clarify})
    samples = [
        Sample("a", "vacation?", country="UA", expected_kind="answer", expected_keywords=("40",)),
        Sample("b", "no country", expected_kind="clarification"),
        Sample("c", "vacation?", expected_kind="clarification"),  # bot answers instead of asking
        Sample("d", "fail please", country="USA", expected_kind="answer"),
        Sample("e", "vacation?", country="USA"),  # kind not checked
    ]
    results = asyncio.run(EvaluationRunner(llm, PROMPT, CHUNKS, concurrency=2, intake_prompt="intake").run(samples))
    by_id = {r.id: r for r in results}

    assert (by_id["a"].kind, by_id["a"].kind_passed, by_id["a"].keywords_passed) == ("answer", True, True)
    assert by_id["a"].sources == ("3-3",) and by_id["a"].model_used == "fake/model"
    assert (by_id["b"].kind, by_id["b"].kind_passed, by_id["b"].answer) == ("clarification", True, "Яка країна?")
    assert by_id["b"].sources is None and by_id["b"].prompt_tokens == 100  # intake call only
    assert (by_id["c"].kind, by_id["c"].kind_passed) == ("answer", False)
    assert by_id["d"].error and by_id["d"].kind is None and by_id["d"].kind_passed is False
    assert by_id["e"].kind_passed is None

    s = summarize(results)
    assert (s["kind_passed"], s["kind_checked"], s["kind_accuracy_pct"]) == (2, 4, 50.0)
    assert s["kinds"] == {"answer": 3, "clarification": 1}


def test_runner_without_intake_always_answers() -> None:
    llm = FakeLLM()
    samples = [Sample("a", "q", expected_kind="clarification")]
    [r] = asyncio.run(EvaluationRunner(llm, PROMPT, CHUNKS, concurrency=1).run(samples))
    assert (r.kind, r.kind_passed) == ("answer", False) and len(llm.calls) == 1


# --- CLI -------------------------------------------------------------------------------------------


def test_resolve_intake(caplog: pytest.LogCaptureFixture) -> None:
    args = argparse.Namespace(no_intake=False, intake_prompt=ROOT / "prompts" / "intake_v2_en.md")
    structured = make_settings(structured_output=StructuredOutputConfig(enabled=True))
    text, name = resolve_intake(structured, args)
    assert name == "intake_v2_en" and "pre-analysis" in text

    assert resolve_intake(structured, argparse.Namespace(**{**vars(args), "no_intake": True})) == (None, None)
    with caplog.at_level("WARNING", logger="hr_compass"):
        assert resolve_intake(make_settings(), args) == (None, None)  # structured output off
    assert "intake skipped" in caplog.text
