"""lint: test the tests (lesson 9, TODO 1), and the reference check."""

from __future__ import annotations

import copy

import pytest

from hr_compass.evaluation.domain.testset import KINDS_MIN, lint, norm, reference_problems, relevant_ids, resolve_cases
from hr_compass.evaluation.infrastructure.files import load_testset
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.infrastructure.files import load_chunks
from hr_compass.shared.settings import Settings
from tests.fakes import chunk


def case(cid="a", kind="exact", must=(("120",),), relevant=("x#1",), **kw) -> dict:
    c = {"id": cid, "kind": kind, "groups": ["all_employees"], "question": "How much for a hotel?",
         "must": [list(m) for m in must], "relevant": list(relevant), "reference": "120 EUR per night."}
    return {**c, **kw}


CHUNKS = {"x#1": "Hotel, per night: 120 EUR.", "x#2": "Taxi 30 EUR per trip."}
GOOD = [case("a"), case("b", must=(("30",),), relevant=("x#2",)),
        case("c", kind="no_answer", must=(), relevant=()), case("d", kind="no_answer", must=(), relevant=())]


def test_the_lessons_check_1():
    assert lint(GOOD, CHUNKS) == []
    bad = [*GOOD, case("e", relevant=("x#9",)), case("f", must=(("45",),)), case("a"),
           case("g", kind="no_answer"), case("h", kind="yes_no")]

    text = "\n".join(lint(bad, CHUNKS))

    for needle in ("x#9", "f:", "duplicate", "g:", "yes_no"):
        assert needle in text


def test_every_problem_is_one_line_naming_its_case():
    problems = lint([*GOOD, case("e", relevant=("x#9",)), case("f", must=(("45",),))], CHUNKS)

    assert problems == ["e: unknown chunk id x#9", "f: `must` fact ['45'] not found in the relevant chunks"]


def test_a_must_group_needs_only_one_option_in_the_chunks():
    assert lint([case("a", must=(("сто двадцять", "120"),)), case("b", must=(("120",), ("per night", "за ніч")))],
                CHUNKS) == []


def test_must_facts_compare_after_norm():
    chunks = {"t#1": "Reject goods above −15 °C."}

    assert lint([case("a", must=(("-15  °c",),), relevant=("t#1",)), case("b", must=(("reject",),), relevant=("t#1",))],
                chunks) == []
    assert norm("−15\xa0°C – OK") == "-15 °c - ok"


@pytest.mark.parametrize(("broken", "needle"), [
    (case("e", relevant=()), "e: no `relevant`"),
    (case("e", must=()), "e: no `must`"),
    (case("e", reference=""), "e: missing field 'reference'"),
    (case("e", groups=[]), "e: missing field 'groups'"),
    (case("e", relevant=({"quote": "breakfast"},)), "e: quote 'breakfast' matches no chunk"),
    (case("e", relevant=({"source": "y", "quote": "120 EUR"},)), "matches no chunk in *y"),
])
def test_incomplete_cases_are_reported(broken, needle):
    assert any(needle in p for p in lint([*GOOD, broken, case("z")], CHUNKS))


def test_quotes_resolve_and_archived_or_unreadable_chunks_are_reported():
    chunks = {"Policies/Handbook.docx#0": chunk("Policies/Handbook.docx#0", "One day per week."),
              "Policies/Archive/Old.docx#0": chunk("Policies/Archive/Old.docx#0", "One day per week."),
              "Contracts/c.docx#0": chunk("Contracts/c.docx#0", "7 days notice.", access=("hr",))}
    ok = case("a", must=(("one day",),), relevant=({"quote": "one  DAY per week"},))
    cases = [ok, case("b", must=(("one day",),), relevant=("Policies/Archive/Old.docx#0",)),
             case("c", must=(("7 days",),), relevant=("Contracts/c.docx#0",))]

    problems = lint(cases, chunks)

    assert relevant_ids(ok, chunks) == ["Policies/Handbook.docx#0"]   # the archived copy is not relevant
    assert problems == ["b: relevant chunk Policies/Archive/Old.docx#0 is an archived copy",
                        "c: relevant chunk Contracts/c.docx#0 is not readable by groups ['all_employees']"]


def test_readability_follows_the_group_hierarchy():
    chunks = {"Contracts/c.docx#0": chunk("Contracts/c.docx#0", "7 days notice.", access=("all_employees",))}
    hr_case = case("a", must=(("7 days",),), relevant=("Contracts/c.docx#0",), groups=["hr"])
    policy = AccessPolicy({}, {"hr": ("all_employees",)})

    assert lint([hr_case, case("b", kind="no_answer", must=(), relevant=())], chunks, kinds_min=1,
                can_read=policy.can_read) == []


def test_a_kind_with_too_few_cases_is_reported():
    assert lint([*GOOD, case("h", kind="yes_no")], CHUNKS) == [f"kind yes_no: 1 case(s), needs at least {KINDS_MIN}"]


def test_a_reference_that_fails_its_own_must_is_reported_separately():
    cases = [case("a"), case("e", reference="One hundred and twenty euros."),
             case("f", must=(("120",), ("night", "ніч"))), case("g", kind="no_answer", must=(), relevant=())]

    assert reference_problems(cases) == ["e: `must` fact ['120'] not found in the reference answer"]
    assert reference_problems(GOOD)[0].startswith("b:")   # the lesson's check 1 has one such case on purpose


def test_resolve_cases_turns_quotes_into_chunk_ids():
    [resolved] = resolve_cases([case("a", relevant=({"quote": "120 EUR"},))], CHUNKS)

    assert resolved["relevant"] == ["x#1"]


# ---------------------------------------------------------------- the real testset


@pytest.fixture(scope="module")
def real():
    settings = Settings.load(env={})
    try:
        chunks = load_chunks(settings.ingest.output_dir)
    except FileNotFoundError:
        pytest.skip("no ingested chunks (run `hr-compass ingest`)")
    policy = AccessPolicy({}, settings.access.inherits)
    return load_testset(settings.eval.testset), {c.chunk_id: c for c in chunks}, policy


def test_the_real_testset_is_clean(real):
    cases, chunks, policy = real

    assert lint(cases, chunks, can_read=policy.can_read) == [] and reference_problems(cases) == []
    assert {c["kind"] for c in cases} >= {"paraphrase", "exact", "cross-lingual", "access", "stale", "no_answer"}


def test_lint_catches_mutations_of_the_real_testset(real):
    cases, chunks, policy = real
    broken = copy.deepcopy(cases)
    broken[0]["must"].append(["seventeen days"])          # a fact the handbook never says
    broken[1]["relevant"] = [{"quote": "$57 per month"}]   # a typo in the quote
    broken[20]["groups"] = ["all_employees"]               # q21 needs hr to read the contract

    problems = lint(broken, chunks, can_read=policy.can_read)

    assert any(p.startswith("q01: `must` fact ['seventeen days']") for p in problems)
    assert any(p.startswith("q02: quote '$57 per month' matches no chunk") for p in problems)
    assert any(p.startswith("q21: relevant chunk") and "not readable" in p for p in problems)
