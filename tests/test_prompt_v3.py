"""Prompt v3: own answer schema (needs_clarification), declared in the prompt file; clarification reply kind."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hr_compass.pipeline import HRCompass
from hr_compass.prompts import PromptError, PromptTemplate
from hr_compass.schema import HRAnswer, HRAnswerV3, parse_model, response_format
from tests.test_chat import FakeLLM, chunk

ROOT = Path(__file__).resolve().parent.parent
V3 = ROOT / "prompts" / "v3_country_clarification.md"
CLARIFY = {"found": False, "answer": "In which country do you work: USA, UA or Costa Rica?", "sources": [],
           "confidence": "low", "needs_clarification": True}
ANSWER = {"found": True, "answer": "18 days.", "sources": ["3-2"], "confidence": "high", "needs_clarification": False}


def test_v3_declares_its_schema_and_hides_the_directive_from_the_model() -> None:
    prompt = PromptTemplate.from_file(V3)
    assert prompt.output_model is HRAnswerV3
    assert "schema:" not in prompt.render(context="CTX") and "CTX" in prompt.render(context="CTX")
    example = prompt.template[prompt.template.rindex("{\"found\"") :].split("\n")[0]  # JSON example in the prompt
    assert HRAnswerV3.model_validate_json(example).needs_clarification is False


def test_older_prompts_keep_the_v2_schema() -> None:
    for name in ("v1_baseline.md", "v2_structured.md"):
        assert PromptTemplate.from_file(ROOT / "prompts" / name).output_model is HRAnswer


def test_unknown_schema_directive_is_rejected(tmp_path: Path) -> None:
    f = tmp_path / "v9.md"
    f.write_text("<!-- schema: nope -->\n{{context}}", encoding="utf-8")
    with pytest.raises(PromptError, match="unknown schema"):
        PromptTemplate.from_file(f)


def test_v3_schema_is_strict_friendly_and_validated() -> None:
    schema = response_format("hr_answer", strict=True, model=HRAnswerV3)["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"]) and schema["additionalProperties"] is False
    assert parse_model(json.dumps(CLARIFY), HRAnswerV3).needs_clarification
    with pytest.raises(ValueError, match="needs_clarification"):
        parse_model(json.dumps({**CLARIFY, "found": True, "sources": ["3-2"]}), HRAnswerV3)


def v3_bot(answer: dict) -> tuple[HRCompass, FakeLLM]:
    llm = FakeLLM(answer=answer)
    chunks = [chunk("3-2", "USA"), chunk("3-2", "UA")]
    return HRCompass(llm, PromptTemplate.from_file(V3), chunks, intake_prompt="intake"), llm


def test_v3_clarification_becomes_a_clarification_reply() -> None:
    bot, llm = v3_bot(CLARIFY)
    reply = asyncio.run(bot.ask("How many vacation days?"))
    assert (reply.kind, reply.text, reply.found) == ("clarification", CLARIFY["answer"], None)
    assert llm.calls[-1][0] is HRAnswerV3  # the answer call asked for the v3 schema
    assert "country: USA" in llm.calls[-1][1][0]["content"] and "country: UA" in llm.calls[-1][1][0]["content"]


def test_v3_answer_and_disabled_clarification_stay_answers() -> None:
    bot, _ = v3_bot(ANSWER)
    assert asyncio.run(bot.ask("q", country="UA")).kind == "answer"
    bot, _ = v3_bot(CLARIFY)  # second chat turn: clarification already asked once
    assert asyncio.run(bot.ask("q", allow_clarification=False)).kind == "answer"
