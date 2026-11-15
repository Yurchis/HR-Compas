"""AskQuestion: intake -> condense -> search -> context -> answer -> citations, and what it logs."""

from __future__ import annotations

import asyncio
import logging

import pytest

from hr_compass.assistant.application.ask_question import AskQuestion, AssistantPrompts
from hr_compass.assistant.domain.answer import RagAnswer, StandaloneQuestion, attribute, validate_citations
from hr_compass.assistant.domain.context import build_context, header
from hr_compass.assistant.domain.intake import Intake
from hr_compass.assistant.domain.reply import NOT_FOUND, OUT_OF_SCOPE
from hr_compass.knowledge.application.search_service import SearchService
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.retrieval import Hit
from hr_compass.shared.llm import LLMError
from hr_compass.shared.tokens import TiktokenTokenizer
from tests.fakes import FakeGenerator, ListRetriever, chunk

CHUNKS = [
    chunk("Usa/handbook.docx#105", "0 – 3 years of service – one day per week.", section="2-5. Remote Work",
          country="USA", title="Employee Handbook", effective="2026-01-01"),
    chunk("UA/vacation.pdf#0", "Employees get 24 calendar days of paid annual leave.", section="Vacation",
          country="UA", title="Paid Vacation"),
    chunk("Contracts/agreement.docx#16", "Either party may terminate upon 7 days' notice.", access=("hr",),
          title="Contractor Agreement"),
]
INTAKE = Intake(language="en", in_scope=True, country=None, needs_clarification=False, clarifying_question=None)


def answer(found=True, text="One day a week.", citations=("S1",), clarify=False) -> RagAnswer:
    return RagAnswer(found=found, answer=text, citations=list(citations), confidence="high",
                     needs_clarification=clarify)


def bot(llm: FakeGenerator, *, intake=True, condense=True, chunks=CHUNKS) -> tuple[AskQuestion, ListRetriever]:
    retriever = ListRetriever(chunks)
    search = SearchService(retriever, AccessPolicy({}, {"hr": ("all_employees",)}), k=5, mode="test")
    prompts = AssistantPrompts("ANSWER", "INTAKE" if intake else None, "CONDENSE" if condense else None)
    return AskQuestion(llm, search, prompts, TiktokenTokenizer("o200k_base"), context_budget=1500), retriever


def ask(b: AskQuestion, question: str = "How many days can I work from home?", **kw):
    return asyncio.run(b.ask(question, groups=kw.pop("groups", ["all_employees"]), **kw))


def test_a_grounded_answer_cites_the_chunk_and_sums_usage():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer()])
    b, _ = bot(llm)

    reply = ask(b)

    assert (reply.kind, reply.found, reply.text) == ("answer", True, "One day a week.")
    assert reply.cited == ("Usa/handbook.docx#105",) and reply.sources == {"Usa/handbook.docx#105": CHUNKS[0].text}
    assert reply.prompt_tokens == 20 and reply.cost_usd == pytest.approx(0.002)   # intake + answer
    [messages] = llm.calls_of("RagAnswer")
    assert messages[0]["content"] == "ANSWER"
    assert "[S1] Employee Handbook · 2-5. Remote Work · USA · effective 2026-01-01" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("Question: How many days can I work from home?")


def test_access_is_enforced_by_the_search_not_the_prompt():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(citations=("S1",)), answer(citations=("S3",))])
    b, retriever = bot(llm)

    employee = ask(b, "contractor notice?")
    ask(b, "contractor notice?", groups=["hr"])

    shown_to_employee = str(llm.calls_of("RagAnswer")[0])
    assert "Contractor Agreement" not in shown_to_employee and "terminate" not in shown_to_employee   # never shown
    assert "Contractor Agreement" in llm.calls_of("RagAnswer")[1][-1]["content"]
    assert retriever.queries[1].groups == {"hr", "all_employees"}   # the hierarchy expanded
    assert employee.cited == ("Usa/handbook.docx#105",)


def test_a_country_named_in_the_question_filters_the_search_and_beats_the_profile():
    llm = FakeGenerator(Intake=[INTAKE.model_copy(update={"country": "UA"})], RagAnswer=[answer()])
    b, retriever = bot(llm)

    reply = ask(b, "vacation in Kyiv?", country="USA")

    assert retriever.queries[0].country == "UA" and reply.cited == ("UA/vacation.pdf#0",)
    assert "country=UA" in str(llm.calls_of("RagAnswer")[0])   # the answer model is told the profile


def test_the_known_profile_is_told_to_intake_so_it_does_not_ask():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer()])

    ask(bot(llm)[0], country="UA")

    assert any("country=UA" in m["content"] for m in llm.calls_of("Intake")[0] if m["role"] == "system")


def test_nothing_readable_found_means_not_found_without_an_answer_call():
    llm = FakeGenerator(Intake=[INTAKE.model_copy(update={"language": "uk"})])
    b, _ = bot(llm, chunks=[CHUNKS[2]])   # only an hr chunk

    reply = ask(b, "Скільки днів?")

    assert (reply.found, reply.text) == (False, NOT_FOUND["uk"]) and llm.calls_of("RagAnswer") == []


def test_citations_of_sources_never_shown_are_dropped():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(citations=("[S1]", "S9")), answer(citations=("S7",))])
    b, _ = bot(llm)

    partly = ask(b)
    invented = ask(b)

    assert partly.cited == ("Usa/handbook.docx#105",) and partly.invalid_citations == ("S9",)
    assert (invented.found, invented.text, invented.cited) == (False, NOT_FOUND["en"], ())


def test_an_honest_not_found_keeps_the_models_words():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(found=False, text="I don't know, ask HR.", citations=())])

    reply = ask(bot(llm)[0])

    assert (reply.found, reply.text, reply.cited) == (False, "I don't know, ask HR.", ())


def test_out_of_scope_and_clarification_skip_the_answer_call():
    out = INTAKE.model_copy(update={"in_scope": False, "language": "ru"})
    clarify = INTAKE.model_copy(update={"needs_clarification": True, "clarifying_question": "Full-time?"})
    llm = FakeGenerator(Intake=[out, clarify, clarify], RagAnswer=[answer()])
    b, _ = bot(llm)

    assert ask(b).text == OUT_OF_SCOPE["ru"]
    assert (ask(b).kind, len(llm.calls_of("RagAnswer"))) == ("clarification", 0)
    assert ask(b, allow_clarification=False).kind == "answer"   # the answer of a clarified question


def test_the_answer_model_may_ask_which_country():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(found=False, text="Which country?", citations=(),
                                                           clarify=True)])

    assert ask(bot(llm)[0]).kind == "clarification"


def test_a_follow_up_is_condensed_before_the_search():
    llm = FakeGenerator(Intake=[INTAKE], StandaloneQuestion=[StandaloneQuestion(question="Remote days after 3 years?")],
                        RagAnswer=[answer()])
    b, retriever = bot(llm)

    reply = ask(b, "And after 3 years?", history=[("How many remote days?", "One day a week.")])

    assert retriever.queries[0].text == reply.query == "Remote days after 3 years?"
    assert "How many remote days?" in llm.calls_of("StandaloneQuestion")[0][-1]["content"]


def test_without_history_or_condense_prompt_there_is_no_condense_call():
    llm = FakeGenerator(Intake=[INTAKE, INTAKE], RagAnswer=[answer(), answer()])
    ask(bot(llm)[0])
    ask(bot(llm, condense=False)[0], history=[("q", "a")])

    assert llm.calls_of("StandaloneQuestion") == []


def test_failed_intake_or_condense_degrade_and_a_failed_answer_raises():
    llm = FakeGenerator(Intake=[LLMError(["m: down"])], StandaloneQuestion=[LLMError(["m: down"])],
                        RagAnswer=[answer(), LLMError(["m: down"])])
    b, retriever = bot(llm)

    assert ask(b, "q2", history=[("q1", "a1")]).found and retriever.queries[0].text == "q2"
    with pytest.raises(LLMError):
        ask(bot(llm, intake=False)[0])


def test_logs_carry_sizes_refs_and_cost_never_the_question_or_chunk_texts(caplog):
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer()])

    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        ask(bot(llm)[0], "SECRET-QUESTION about home office", rid="r1")

    info = [r for r in caplog.records if r.levelno >= logging.INFO]
    rendered = " ".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in info)
    assert "SECRET-QUESTION" not in rendered and "one day per week" not in rendered and "handbook" not in rendered
    assert CHUNKS[0].ref in rendered and all(r.request_id == "r1" for r in info)
    done = next(r for r in info if r.getMessage() == "ask done")
    assert done.fields["found"] is True and done.fields["context_tokens"] > 0 and done.fields["cost"] > 0
    assert any("SECRET-QUESTION" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)


# ---------------------------------------------------------------- context and citations


def test_the_context_labels_sources_and_respects_the_budget():
    tok = TiktokenTokenizer("o200k_base")
    long = chunk("x#0", "word " * 2000)
    hits = [Hit(CHUNKS[0], 1.0), Hit(long, 0.9), Hit(CHUNKS[1], 0.8)]

    context = build_context(hits, 200, tok)

    assert list(context.sources) == ["S1", "S2"] and context.sources["S2"] == CHUNKS[1]   # the long one skipped
    assert context.tokens <= 200 and context.text.startswith(header("S1", CHUNKS[0]))
    assert header("S2", CHUNKS[1]) == "[S2] Paid Vacation · Vacation · UA"
    assert "company-wide" in header("S1", CHUNKS[2])


@pytest.mark.parametrize(("text", "expected_text", "labels", "statements", "uncited"), [
    ("One day a week [S1]. Two days after 3 years [S1].", "One day a week [1]. Two days after 3 years [1].",
     ("S1",), 2, 0),
    ("Overtime is 1.5 times the wage [S2]. Leave is 24 days [S1, S2].",              # "1.5" is not a stop
     "Overtime is 1.5 times the wage [1]. Leave is 24 days [2, 1].", ("S2", "S1"), 2, 0),
    ("One day a week. [S1] Ask your manager to agree the day.",                       # a marker after the stop counts
     "One day a week. [1] Ask your manager to agree the day.", ("S1",), 2, 1),
    ("Відпустка 24 дні [S2]. Невикористані дні згорають [S9].", "Відпустка 24 дні [1]. Невикористані дні згорають.",
     ("S2",), 2, 1),                                                                 # S9 was not shown: dropped
])
def test_attribute_renumbers_inline_labels_and_counts_statements_without_a_source(text, expected_text, labels,
                                                                                 statements, uncited):
    a = attribute(text, [], {"S1", "S2", "S3"})

    assert (a.text, a.labels, a.statements, a.uncited) == (expected_text, labels, statements, uncited)
    assert a.invalid == (("S9",) if "S9" in text else ())


def test_a_source_only_in_the_citation_list_is_still_used_after_the_inline_ones():
    a = attribute("Leave is 24 days [S2].", ["S1", "S2", "S7"], {"S1", "S2"})

    assert a.labels == ("S2", "S1") and a.invalid == ("S7",) and a.text == "Leave is 24 days [1]."


def test_inline_citations_reach_the_reply_numbered_as_the_sources_are_listed():
    text = "One day a week [S1]. In Ukraine leave is 24 days [S2]."
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(text=text, citations=("S2", "S1"))])
    b, _ = bot(llm)

    reply = ask(b)

    assert reply.text == "One day a week [1]. In Ukraine leave is 24 days [2]."
    assert reply.cited == ("Usa/handbook.docx#105", "UA/vacation.pdf#0")      # [1], [2]: order of first use
    assert (reply.statements, reply.uncited_statements) == (2, 0)
    assert reply.as_result()["attributed"] is True


def test_an_answer_whose_only_labels_were_never_shown_is_not_found():
    llm = FakeGenerator(Intake=[INTAKE], RagAnswer=[answer(text="One day a week [S7].", citations=())])
    b, _ = bot(llm)

    reply = ask(b)

    assert reply.found is False and reply.text == NOT_FOUND["en"] and reply.invalid_citations == ("S7",)
    assert reply.as_result()["attributed"] is None


def test_validate_citations_normalises_and_splits_valid_and_invalid():
    assert validate_citations(["[S1]", " S1 ", "S4"], {"S1", "S2"}) == (["S1"], ["S4"])


def test_a_clarification_cannot_cite_sources():
    with pytest.raises(ValueError, match="needs_clarification"):
        answer(found=False, citations=("S1",), clarify=True)
