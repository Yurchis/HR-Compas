"""The LLM judge (lesson 9, TODO 4-6), calibration (TODO 5) and the ChatLLM adapter.

The live tests ask the real judge (OpenRouter, ~$0.001):
    HR_COMPASS_LIVE=1 python -m pytest tests/evaluation/test_judge.py
"""

from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv

from hr_compass.evaluation.application.judges import LlmJudge
from hr_compass.evaluation.domain.judging import CLAIMS_FORMAT, VERDICT_FORMAT, JudgeError, Verdict
from hr_compass.evaluation.domain.scores import calibrate
from hr_compass.evaluation.infrastructure.files import LabelError, load_labels
from hr_compass.shared.chat_llm import ChatLLM
from hr_compass.shared.paths import ROOT
from hr_compass.shared.prompts import PromptError, judge_prompt
from hr_compass.shared.settings import Settings
from tests.fakes import FakeChat, completion

LIVE = pytest.mark.skipif(os.environ.get("HR_COMPASS_LIVE") != "1", reason="live: set HR_COMPASS_LIVE=1 (OpenRouter)")
CASE = {"id": "q12", "kind": "paraphrase", "question": "How many days of annual leave do employees in Ukraine have?",
        "reference": "24 calendar days of paid annual leave a year."}
NOT_FOUND = "I could not find this in the documents available to you."
PROBATION = ("The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax "
             "Analysts, the adaptation period is 1 month).")


def judge(llm) -> LlmJudge:
    return LlmJudge(llm, judge_prompt("judge-v3", "correct"), judge_prompt("judge-v3", "grounded"))


def _verdict(verdict="correct", reason="Same value: 24 days.") -> str:
    return json.dumps({"reason": reason, "verdict": verdict})


def _claims(*claims: tuple[str, bool]) -> str:
    return json.dumps({"claims": [{"claim": c, "supported": s} for c, s in claims]})


# ---------------------------------------------------------------- correctness (TODO 4)


def test_the_judge_sends_the_prompt_question_reference_and_answer_and_parses_a_verdict():
    llm = FakeChat([_verdict()])

    v = judge(llm).correct(CASE, "You get twenty-four calendar days a year.")

    assert isinstance(v, Verdict) and v.verdict == "correct"
    [asked] = llm.asked
    system, user = asked["messages"]
    assert system == {"role": "system", "content": judge_prompt("judge-v3", "correct")}
    for part in (CASE["question"], CASE["reference"], "twenty-four calendar days"):
        assert part in user["content"]
    assert user["content"].index("<reference>") < user["content"].index("<answer>")
    assert asked["schema"] == VERDICT_FORMAT


def test_a_fenced_json_reply_is_accepted():
    assert judge(FakeChat([f"```json\n{_verdict('incorrect')}\n```"])).correct(CASE, "20 days").verdict == "incorrect"


@pytest.mark.parametrize("reply", ["Correct!", json.dumps({"verdict": "maybe", "reason": "?"}),
                                   json.dumps({"verdict": "correct"})])
def test_a_reply_that_is_not_a_verdict_is_a_judge_error(reply):
    with pytest.raises(JudgeError, match="q12"):
        judge(FakeChat([reply])).correct(CASE, "24 days")


def test_reason_comes_before_verdict_in_a_strict_schema():
    assert list(VERDICT_FORMAT["json_schema"]["schema"]["properties"]) == ["reason", "verdict"]
    assert VERDICT_FORMAT["json_schema"]["strict"] is True


def test_the_judge_prompt_is_the_calibrated_version():
    assert "key fact" in judge_prompt("judge-v3", "correct")
    with pytest.raises(PromptError, match="judge-v9"):
        judge_prompt("judge-v9", "correct")


# ---------------------------------------------------------------- groundedness (TODO 6)


def test_a_not_found_answer_is_not_judged_and_costs_nothing():
    llm = FakeChat()

    assert judge(llm).grounded(NOT_FOUND, False, []) == (None, []) and llm.asked == []


def test_grounded_returns_the_unsupported_claims():
    llm = FakeChat([_claims(("Probation is 3 months", True), ("It can be extended by 2 months", False))])

    got = judge(llm).grounded("Probation is 3 months; it can be extended by 2 months.", True, [PROBATION])

    assert got == (False, ["It can be extended by 2 months"])
    [asked] = llm.asked
    system, user = asked["messages"]
    assert system["content"] == judge_prompt("judge-v3", "grounded")
    assert PROBATION in user["content"] and user["content"].index("<sources>") < user["content"].index("<answer>")
    assert asked["schema"] == CLAIMS_FORMAT


def test_all_claims_supported_or_no_claims_at_all_is_grounded():
    assert judge(FakeChat([_claims(("3 months", True))])).grounded("3 months.", True, [PROBATION]) == (True, [])
    assert judge(FakeChat([_claims()])).grounded("Hope this helps!", True, [PROBATION]) == (True, [])


def test_sources_are_numbered_and_an_uncited_answer_says_so():
    llm = FakeChat([_claims(("x", False)), _claims(("x", False))])

    judge(llm).grounded("x", True, ["first source", "second source"])
    judge(llm).grounded("x", True, [])

    assert "[S1]\nfirst source" in llm.asked[0]["messages"][1]["content"]
    assert "[S2]\nsecond source" in llm.asked[0]["messages"][1]["content"]
    assert "(no sources cited)" in llm.asked[1]["messages"][1]["content"]


def test_a_reply_that_is_not_claims_is_a_judge_error():
    with pytest.raises(JudgeError, match="not Claims"):
        judge(FakeChat([json.dumps({"claims": [{"claim": "x"}]})])).grounded("x", True, [PROBATION])


# ---------------------------------------------------------------- calibrate (TODO 5)


def test_calibrate_the_lessons_check_5():
    c = calibrate([True, True, False, True, False], [True, False, False, True, True], list("abcde"))

    assert c["agreement"] == pytest.approx(0.6)
    assert c["false_pass"] == pytest.approx(0.2) and c["false_fail"] == pytest.approx(0.2)
    assert c["disagreements"] == ["b", "e"]


def test_agreement_plus_both_errors_is_one():
    c = calibrate([True, False, True, True], [False, False, True, False], ["a", "b", "c", "d"])

    assert c["agreement"] + c["false_pass"] + c["false_fail"] == pytest.approx(1.0) and c["false_fail"] == 0


def test_hand_labels_without_a_verdict_are_refused_before_any_judge_call(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps([{"id": "q01-a", "correct": True}, {"id": "q02-b", "correct": None},
                                {"id": "q03-c"}]), encoding="utf-8")

    with pytest.raises(LabelError, match=r"2 of 3 .* q02-b q03-c"):
        load_labels(path)
    path.write_text(json.dumps([{"id": "q01-a", "correct": False}]), encoding="utf-8")
    assert load_labels(path) == [{"id": "q01-a", "correct": False}]


def test_calibrate_checks_lengths_and_handles_nothing():
    with pytest.raises(ValueError, match="length"):
        calibrate([True], [True, False], ["a", "b"])
    assert calibrate([], [], []) == {"agreement": None, "false_pass": None, "false_fail": None, "disagreements": []}


# ---------------------------------------------------------------- the ChatLLM adapter


class FakeClient:
    def __init__(self) -> None:
        self.requests, self.closed = [], False

    async def complete(self, messages, *, model, response_format=None):
        self.requests.append((messages, model, response_format))
        return completion(_verdict(), prompt_tokens=100, completion_tokens=20, cost=0.0001)

    async def __aexit__(self, *exc):
        self.closed = True


def test_chat_llm_passes_the_schema_and_adds_up_usage():
    client, settings = FakeClient(), Settings.load(env={"OPENROUTER_API_KEY": "k"})

    with ChatLLM(settings, client=client) as llm:
        judge(llm).correct(CASE, "24 days")
        judge(llm).correct(CASE, "24 days")

    assert [r[2] for r in client.requests] == [VERDICT_FORMAT, VERDICT_FORMAT]
    assert client.requests[0][1] == settings.model and client.closed
    assert (llm.calls, llm.tokens_in, llm.tokens_out) == (2, 200, 40) and llm.cost() == pytest.approx(0.0002)


# ---------------------------------------------------------------- the real judge


@LIVE
def test_the_real_judge_tells_right_from_wrong():
    load_dotenv(ROOT / ".env")
    no_answer = {"id": "q24", "question": "Does the company reimburse a gym membership?",
                 "reference": "The documents do not say: the bot must say it has no information."}
    with ChatLLM(Settings.load()) as llm:
        j = judge(llm)
        verdicts = {
            "right": j.correct(CASE, "Employees in Ukraine get 24 calendar days of paid vacation per year."),
            "wrong": j.correct(CASE, "Employees in Ukraine get 28 calendar days of paid vacation per year."),
            "ukrainian": j.correct(CASE, "Працівники в Україні мають 24 календарні дні оплачуваної відпустки."),
            "abstained": j.correct(no_answer, NOT_FOUND),
            "invented": j.correct(no_answer, "Yes, up to $50 a month for a gym membership."),
        }
    assert {n: v.verdict for n, v in verdicts.items()} == {
        "right": "correct", "wrong": "incorrect", "ukrainian": "correct", "abstained": "correct",
        "invented": "incorrect"}


@LIVE
def test_the_real_groundedness_check_catches_an_added_rule():
    load_dotenv(ROOT / ".env")
    with ChatLLM(Settings.load()) as llm:
        j = judge(llm)
        results = {
            "faithful": j.grounded("Probation lasts 3 months, or 1 month for Affordable Housing and Property Tax "
                                   "Analysts.", True, [PROBATION]),
            "ukrainian": j.grounded("Випробувальний термін — 3 місяці.", True, [PROBATION]),
            "added rule": j.grounded("Probation lasts 3 months and can be extended once by another 2 months.",
                                     True, [PROBATION]),
            "wrong number": j.grounded("Probation lasts 6 months.", True, [PROBATION]),
            "not found": j.grounded(NOT_FOUND, False, []),
        }
    assert {n: ok for n, (ok, _) in results.items()} == {
        "faithful": True, "ukrainian": True, "added rule": False, "wrong number": False, "not found": None}
