"""Retrieval metrics (recall@k, MRR, leaks), the access check, gate metrics, semantic near-duplicates."""

from __future__ import annotations

import pytest

from hr_compass.evaluation.application.eval_retrieval import run_retrieval_eval
from hr_compass.evaluation.application.similar_pairs import similar_pairs
from hr_compass.evaluation.domain.retrieval_metrics import (
    QuestionError,
    check_access,
    cosine,
    evaluate,
    gate_metrics,
    retrieval_questions,
)
from hr_compass.evaluation.domain.scores import gate
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.retrieval import Hit
from tests.fakes import ListRetriever, chunk

CHUNKS = {c.chunk_id: c for c in [
    chunk("Policies/Handbook 2026.docx#0", "Employees may work remotely\n one day per week."),
    chunk("Policies/Archive/DNU Handbook.docx#0", "Employees may work remotely one day per week.", access=("hr",)),
    chunk("Notes/remote.docx#0", "Remote work: ONE DAY PER WEEK."),
]}
POLICY = AccessPolicy({}, {"hr": ("all_employees",)})


def hits(*ids: str, access=("all_employees",)) -> list[Hit]:
    return [Hit(chunk(i, access=access), 1.0) for i in ids]


# ---------------------------------------------------------------- questions


def test_quotes_resolve_to_chunk_ids_ignoring_case_spacing_and_archived_copies():
    questions = retrieval_questions([
        {"id": "a", "question": "?", "groups": [], "kind": "paraphrase", "relevant": [{"quote": "one day  per week"}]},
        {"id": "b", "question": "?", "groups": [], "kind": "paraphrase",
         "relevant": [{"source": "Handbook 2026.docx", "quote": "one day per week"}, "Notes/remote.docx#0"]},
        {"id": "c", "question": "?", "groups": [], "kind": "no_answer"},
    ], CHUNKS)

    assert [q["id"] for q in questions] == ["a", "b"]   # no_answer: nothing to retrieve
    assert questions[0]["relevant"] == ["Policies/Handbook 2026.docx#0", "Notes/remote.docx#0"]   # no Archive/ copy
    assert questions[1]["relevant"] == ["Policies/Handbook 2026.docx#0", "Notes/remote.docx#0"]


@pytest.mark.parametrize("cases", [
    [{"id": "a", "question": "?", "groups": [], "relevant": [{"quote": "not in any chunk"}]}],
    [{"id": "a", "question": "?", "groups": [], "relevant": [{"source": "Other.pdf", "quote": "one day per week"}]}],
    [{"id": "a", "question": "?", "groups": [], "relevant": ["Notes/remote.docx#0"]},
     {"id": "a", "question": "?", "groups": [], "relevant": ["Notes/remote.docx#0"]}],
    [{"id": "a", "question": "?", "groups": [], "relevant": ["Unknown/x.docx#9"]}],
])
def test_a_label_that_matches_nothing_or_a_duplicate_id_is_an_error(cases):
    with pytest.raises(QuestionError):
        retrieval_questions(cases, CHUNKS)


def test_lenient_drops_a_cut_quote_and_keeps_its_question_as_a_certain_miss():
    cases = [{"id": "a", "question": "?", "groups": [], "relevant": [{"quote": "cut by the chunking"},
                                                                       "Notes/remote.docx#0"]},
             {"id": "b", "question": "?", "groups": [], "relevant": [{"quote": "not in any chunk"}]}]

    questions = retrieval_questions(cases, CHUNKS, strict=False)

    assert [(q["id"], q["relevant"]) for q in questions] == [("a", ["Notes/remote.docx#0"]), ("b", [])]
    r = evaluate(lambda *_: hits("Notes/remote.docx#0"), questions, k=5, can_read=lambda *_: True)
    assert r["recall"] == pytest.approx(0.5) and r["misses"] == ["b"]
    with pytest.raises(QuestionError):   # duplicates stay an error even when lenient
        retrieval_questions([cases[0], cases[0]], CHUNKS, strict=False)


# ---------------------------------------------------------------- recall@k and MRR


def test_recall_and_mrr_on_the_lessons_fake_example():
    fake = {"a": ["x", "r1", "y"], "b": ["r2", "x"], "c": ["x", "y", "z"]}
    qs = [{"id": "a", "question": "a", "groups": [], "relevant": ["r1"], "kind": "k"},
          {"id": "b", "question": "b", "groups": [], "relevant": ["r2"], "kind": "k"},
          {"id": "c", "question": "c", "groups": [], "relevant": ["r3"], "kind": "k"}]

    r = evaluate(lambda q, g: hits(*fake[q]), qs, k=5, can_read=lambda access, groups: True)

    assert r["recall"] == pytest.approx(2 / 3) and r["mrr"] == pytest.approx(0.5)
    assert r["misses"] == ["c"] and r["ranks"] == {"a": 2, "b": 1, "c": None} and r["leaks"] == 0


def test_only_the_top_k_counts_and_any_relevant_chunk_is_enough():
    q = [{"id": "a", "question": "a", "groups": [], "relevant": ["r1", "r2"], "kind": "k"}]
    ranking = hits("x", "y", "r2", "r1")

    assert evaluate(lambda *_: ranking, q, k=2, can_read=POLICY.can_read)["recall"] == 0
    assert evaluate(lambda *_: ranking, q, k=3, can_read=lambda *_: True)["mrr"] == pytest.approx(1 / 3)
    assert evaluate(lambda *_: [], [], k=5, can_read=POLICY.can_read)["recall"] == 0


def test_context_tokens_is_the_mean_size_of_the_top_k_the_answer_model_would_read():
    q = [{"id": i, "question": i, "groups": [], "relevant": ["r"], "kind": "k"} for i in ("a", "b")]
    long, short = Hit(chunk("r", "one two three four"), 1.0), Hit(chunk("s", "five six"), 1.0)
    ranking = {"a": [long, short, short], "b": [short]}

    r = evaluate(lambda question, _: ranking[question], q, k=2, can_read=lambda *_: True)

    assert r["context_tokens"] == pytest.approx(((4 + 2) + 2) / 2)   # only the top-2 of "a" count


def test_hits_the_user_may_not_read_are_counted_as_leaks_with_the_hierarchy():
    q = [{"id": "a", "question": "a", "groups": ["all_employees"], "relevant": ["r"], "kind": "k"}]
    mixed = hits("r") + hits("s", access=("hr",))

    assert evaluate(lambda *_: mixed, q, k=5, can_read=POLICY.can_read)["leaks"] == 1
    q[0]["groups"] = ["hr"]   # hr includes all_employees: no leak
    assert evaluate(lambda *_: mixed, q, k=5, can_read=POLICY.can_read)["leaks"] == 0


def test_check_access_asks_access_questions_as_an_ordinary_employee():
    qs = [{"id": "a", "question": "contractor fee", "groups": ["all_employees", "hr"], "relevant": []},
          {"id": "b", "question": "vacation", "groups": ["all_employees"], "relevant": []}]
    asked: list[tuple] = []

    def leaky(q, g):
        asked.append((q, tuple(g)))
        return hits("c", access=("hr",))

    leaks = check_access({"leaky": leaky, "safe": lambda q, g: hits("v")}, qs, POLICY.can_read)

    assert leaks == {"leaky": 1, "safe": 0} and asked == [("contractor fee", ("all_employees",))]


def test_gate_metrics_flatten_a_run_for_the_gate():
    results = {"vector": {"recall": 0.7, "mrr": 0.5, "leaks": 0, "misses": ["q01"], "ms": 14.0},
               "bm25": {"recall": 0.5, "mrr": 0.4, "leaks": 0, "misses": [], "ms": 2.0}}
    qs = [{"id": "q01"}, {"id": "q02"}]

    flat = gate_metrics(results, qs, {"vector": 0, "bm25": 2})

    assert flat == {"vector/recall": 0.7, "vector/mrr": 0.5, "vector/leaks": 0,
                    "bm25/recall": 0.5, "bm25/mrr": 0.4, "bm25/leaks": 2, "failed": ["vector:q01"],
                    "cases": ["vector:q01", "vector:q02", "bm25:q01", "bm25:q02"]}   # no ms: machine noise
    worse = gate_metrics({**results, "bm25": {**results["bm25"], "misses": ["q02"]}}, qs, {"vector": 0, "bm25": 2})
    assert gate(worse, flat) == ["regression: bm25:q02"]


def test_run_retrieval_eval_over_configurations():
    questions = retrieval_questions([{"id": "a", "kind": "paraphrase", "question": "remote", "groups": ["hr"],
                                      "relevant": [{"quote": "one day per week"}]}], CHUNKS)
    configs = {"list": ListRetriever(list(CHUNKS.values()))}

    report = run_retrieval_eval(configs, questions, POLICY, k=5)

    assert report.results["list"]["recall"] == 1.0 and report.results["list"]["recall_by_kind"] == {"paraphrase": 1.0}
    assert report.access_ok and configs["list"].queries[0].groups == {"hr", "all_employees"}   # expanded


def test_cosine():
    assert cosine([1, 0], [2, 0]) == pytest.approx(1.0) and cosine([1, 0], [0, 3]) == pytest.approx(0.0)


# ---------------------------------------------------------------- semantic near-duplicates


class TableEmbedder:
    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.table[t] for t in texts]


def _chunks(*items: tuple[str, str]):
    return [chunk(f"{src}#0", text, section="") for src, text in items]


def test_similar_pairs_rank_by_angle_never_inside_one_document():
    table = {"a1": [10.0, 0.0], "a2": [9.0, 1.0], "b": [1.0, 0.05], "c": [0.0, 1.0], "d": [3.0, 1.0]}
    pool = [chunk("A#0", "a1"), chunk("A#1", "a2"), chunk("B#0", "b"), chunk("C#0", "c"), chunk("D#0", "d")]

    pairs = similar_pairs(pool, TableEmbedder(table), top=3)

    assert (pairs[0][1], pairs[0][2]) == ("A#0", "B#0")   # by angle, not by length (10 vs 1): not a dot product
    assert len(pairs) == 3 and all(-1 <= s <= 1 for s, *_ in pairs)
    assert all(a.split("#")[0] != b.split("#")[0] for _, a, b in pairs)


def test_similar_pairs_skip_identical_texts_and_near_copies_but_keep_paraphrases():
    copy_a = "Employees may work remotely one day per week on Wednesday or Thursday."
    copy_b = "Employees may work remotely one day per week on Wednesday or Thursday!"
    paraphrase = "Staff can do home office once a week."
    table = {copy_a: [1.0, 0.0], copy_b: [1.0, 0.0], paraphrase: [1.0, 0.2], "same": [0.0, 1.0]}
    pool = _chunks(("A", copy_a), ("B", copy_b), ("C", paraphrase), ("D", "same"), ("E", "same"))

    pairs = [(a, b) for _, a, b in similar_pairs(pool, TableEmbedder(table), top=10)]

    assert ("A#0", "B#0") not in pairs and ("D#0", "E#0") not in pairs
    assert ("A#0", "C#0") in pairs and ("B#0", "C#0") in pairs
    assert similar_pairs(pool[:1], TableEmbedder(table)) == []
