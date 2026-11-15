"""evaluation.domain.scores: deterministic answer scores, run metrics, stability, the gate (lesson 9)."""

from __future__ import annotations

import pytest

from hr_compass.evaluation.domain.scores import TOLERANCE, aggregate, gate, rate, score, stability
from hr_compass.evaluation.domain.testset import resolve_cases
from hr_compass.evaluation.infrastructure.files import load_testset
from hr_compass.knowledge.infrastructure.files import load_chunks
from hr_compass.shared.settings import Settings

NOT_FOUND = "I could not find this in the documents available to you."


def case(cid="a", kind="exact", must=(("120",),), relevant=("x#1",), **kw) -> dict:
    c = {"id": cid, "kind": kind, "groups": ["all_employees"], "question": "How much for a hotel?",
         "must": [list(m) for m in must], "relevant": list(relevant), "reference": "120 EUR per night."}
    return {**c, **kw}


def result(found=True, answer="120 EUR per night.", cited=("x#1",)) -> dict:
    return {"found": found, "answer": answer, "cited": list(cited)}


NO_ANSWER = case(kind="no_answer", must=(), relevant=())


# ---------------------------------------------------------------- the lesson's check 2


def test_a_good_answer_passes() -> None:
    assert score(result(), case()) == {"facts": True, "cited": True, "abstain": None, "pass": True,
                                          "attributed": None}


def test_facts_compare_after_norm() -> None:
    assert score(result(answer="Reject above −15 °C."), case(must=(("-15 °c",),)))["facts"]


def test_the_right_fact_from_the_wrong_source_fails() -> None:
    s = score(result(cited=("x#5",)), case())

    assert s["facts"] and not s["cited"] and not s["pass"]


def test_abstaining_on_an_answerable_case_fails() -> None:
    s = score(result(found=False, answer=NOT_FOUND, cited=()), case())

    assert s == {"facts": False, "cited": False, "abstain": None, "pass": False, "attributed": None}


def test_abstaining_on_a_no_answer_case_passes_and_answering_it_fails() -> None:
    assert score(result(found=False, answer=NOT_FOUND, cited=()), NO_ANSWER) == \
        {"facts": None, "cited": None, "abstain": True, "pass": True, "attributed": None}
    s = score(result(), NO_ANSWER)
    assert s["abstain"] is False and not s["pass"]


# ---------------------------------------------------------------- beyond the lesson


def test_every_must_group_needs_one_option() -> None:
    c = case(must=(("one day", "один день"), ("two days", "два дні")))

    assert score(result(answer="Один день на тиждень, після 3 років — два дні."), c)["facts"]
    assert not score(result(answer="One day a week."), c)["facts"]   # the second group is missing


def test_found_with_the_fact_but_marked_not_found_is_not_facts() -> None:
    # a bot that says "not found" but leaks the number anyway did not answer
    assert score(result(found=False, answer="Not found. Maybe 120?", cited=()), case())["facts"] is False


def test_any_relevant_chunk_among_several_cited_counts() -> None:
    c = case(relevant=("x#1", "y#2"))

    assert score(result(cited=("z#0", "y#2")), c)["cited"]
    assert not score(result(cited=()), c)["cited"]


def test_unresolved_quotes_are_refused_not_scored_as_uncited() -> None:
    with pytest.raises(ValueError, match="resolve_cases"):
        score(result(), case(relevant=({"quote": "120 EUR"},)))


def test_rate_skips_scores_that_do_not_apply() -> None:
    assert rate([True, False, None, True]) == pytest.approx(2 / 3)
    assert rate([None, None]) is None and rate([]) is None


def test_aggregate_over_a_run() -> None:
    cases = [case("a"), case("b"), case("c", kind="no_answer", must=(), relevant=()), case("d", kind="paraphrase")]
    results = [result(), result(found=False, answer=NOT_FOUND, cited=()),
               result(found=False, answer=NOT_FOUND, cited=()), result(cited=("x#9",))]
    scores = [score(r, c) for r, c in zip(results, cases, strict=True)]

    m = aggregate(scores, cases, results)

    assert m["pass"] == pytest.approx(2 / 4) and m["facts"] == pytest.approx(2 / 3)
    assert m["cited"] == pytest.approx(1 / 3) and m["abstain"] == 1.0
    assert m["false_abstain"] == pytest.approx(1 / 3)   # b gave up on an answerable question
    assert m["by_kind"] == {"exact": 0.5, "no_answer": 1.0, "paraphrase": 0.0}
    assert m["failed"] == ["b", "d"] and "judge" not in m


# ---------------------------------------------------------------- stability (TODO 3)

P, F = {"pass": True}, {"pass": False}


def test_stability_the_lessons_check_3() -> None:
    st = stability([[P, P, F], [P, F, F], [P, P, F]], [case("a"), case("b"), case("c")])

    assert st["rates"] == {"a": 1.0, "b": pytest.approx(2 / 3), "c": 0.0}
    assert st["pass_at_1"] == pytest.approx(5 / 9) and st["pass_all"] == pytest.approx(1 / 3)
    assert st["flaky"] == ["b"]


def test_one_run_has_no_flaky_cases_and_pass_at_1_equals_pass_all() -> None:
    st = stability([[P, F, P]], [case("a"), case("b"), case("c")])

    assert st["flaky"] == [] and st["pass_at_1"] == st["pass_all"] == pytest.approx(2 / 3)


def test_flaky_keeps_testset_order() -> None:
    cases = [case("q09"), case("q02"), case("q15")]

    assert stability([[F, P, P], [P, F, P]], cases)["flaky"] == ["q09", "q02"]


def test_a_run_with_a_missing_score_is_an_error_not_a_silent_cut() -> None:
    with pytest.raises(ValueError, match="one score per case"):
        stability([[P, P], [P]], [case("a"), case("b")])


def test_no_runs() -> None:
    assert stability([], [case("a")]) == {"pass_at_1": None, "pass_all": None, "flaky": [], "rates": {}}


# ---------------------------------------------------------------- the gate (TODO 7)

BASE = {"pass": 0.90, "facts": 0.90, "abstain": 1.0, "false_abstain": 0.03, "grounded": 0.95, "failed": ["q09"]}


def test_gate_the_lessons_check_7() -> None:
    same = {"pass": 0.87, "facts": 0.92, "abstain": 1.0, "false_abstain": 0.06, "grounded": 0.95, "failed": ["q09"]}
    assert gate(same, BASE) == []

    worse = {"pass": 0.80, "facts": 0.90, "abstain": 0.71, "false_abstain": 0.10, "grounded": 0.95,
             "failed": ["q09", "q16", "q20"]}
    got = gate(worse, BASE)

    assert got == ["pass: 0.90 -> 0.80 (-0.10)", "abstain: 1.00 -> 0.71 (-0.29)",
                   "false_abstain: 0.03 -> 0.10 (+0.07)", "regression: q16", "regression: q20"]


def test_a_drop_of_exactly_the_tolerance_passes_despite_float_noise() -> None:
    assert TOLERANCE < 0.90 - 0.85   # the float trap the gate must not fall into
    assert gate({"pass": 0.85, "failed": []}, {"pass": 0.90, "failed": []}) == []


def test_improvements_never_fail_the_gate() -> None:
    better = {"pass": 1.0, "facts": 1.0, "abstain": 1.0, "false_abstain": 0.0, "grounded": 1.0, "failed": []}

    assert gate(better, BASE) == []
    assert gate(better, BASE | {"facts": None}) == []   # a baseline value that was not measured is not checked


def test_a_metric_the_run_did_not_measure_fails_closed() -> None:
    now = {"pass": 0.9, "facts": 0.9, "abstain": 1.0, "false_abstain": 0.03, "grounded": None, "failed": ["q09"]}

    assert gate(now, BASE) == ["grounded: 0.95 in the baseline, not measured now"]


def test_config_metrics_and_leaks() -> None:
    base = {"hybrid+rerank/recall": 0.83, "hybrid+rerank/leaks": 0, "failed": []}

    assert gate({"hybrid+rerank/recall": 0.83, "hybrid+rerank/leaks": 1, "failed": []}, base) == \
        ["hybrid+rerank/leaks: 0.00 -> 1.00 (+1.00)"]


def test_a_case_added_after_the_baseline_is_not_a_regression() -> None:
    base = {"pass": 1.0, "failed": [], "cases": ["q01", "q02"]}

    assert gate({"pass": 1.0, "failed": ["q02", "q27"]}, base) == ["regression: q02"]


# ---------------------------------------------------------------- the real testset


def test_reference_answers_citing_the_relevant_chunks_pass_the_real_testset() -> None:
    """A perfect bot (answer = reference, cites the first relevant chunk, abstains on no_answer) must pass
    every case: otherwise a `must` option is missing from the reference and the case can never pass."""
    settings = Settings.load(env={})
    try:
        chunks = {c.chunk_id: c for c in load_chunks(settings.ingest.output_dir)}
    except FileNotFoundError:
        pytest.skip("no ingested chunks (run `hr-compass ingest`)")
    cases = resolve_cases(load_testset(settings.eval.testset), chunks)
    perfect = [result(found=False, answer=NOT_FOUND, cited=()) if c["kind"] == "no_answer"
               else result(answer=c["reference"], cited=c["relevant"][:1]) for c in cases]

    scores = [score(r, c) for r, c in zip(perfect, cases, strict=True)]

    assert [c["id"] for c, s in zip(cases, scores, strict=True) if not s["pass"]] == []
