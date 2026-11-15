"""AskQuestion: one employee question -> a reply grounded in the documents the employee may read (RAG).

    intake (language, scope, country)  -> out of scope / clarifying question, no answer call
    condense (follow-ups only)         -> a standalone question
    search (groups, country)           -> hits; none -> "not found", no answer call
    context (token budget, [S1] labels) -> answer model (JSON: found, answer with [S1] after each statement, citations)
    citations checked                  -> cited chunk_ids, markers renumbered [1] [2] as the sources are listed,
                                          statements without a source counted; nothing valid cited -> "not found"

Logged per question at INFO: sizes, groups, country, retrieval refs and scores, context tokens, found, cited refs,
tokens, cost, timings. The question text only at DEBUG; chunk texts never.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from hr_compass.assistant.domain.answer import MARKER, RagAnswer, StandaloneQuestion, attribute
from hr_compass.assistant.domain.context import Context, build_context
from hr_compass.assistant.domain.intake import Intake, profile_note
from hr_compass.assistant.domain.reply import NOT_FOUND, OUT_OF_SCOPE, Reply, ReplyKind, message
from hr_compass.knowledge.domain.retrieval import Hit
from hr_compass.shared.llm import LLMError, LLMResult
from hr_compass.shared.logging import kv, log_context
from hr_compass.shared.tokens import Tokenizer

logger = logging.getLogger(__name__)

Turn = tuple[str, str]   # (question, answer) of an earlier exchange


class Generator(Protocol):
    async def generate(self, messages: list[dict[str, str]], *, output_model: type[BaseModel]) -> LLMResult: ...


class Search(Protocol):
    def search(self, text: str, groups: Iterable[str], country: str | None = None,
               k: int | None = None) -> list[Hit]: ...


@dataclass(frozen=True, slots=True)
class AssistantPrompts:
    answer: str
    intake: str | None = None       # None: no intake step
    condense: str | None = None     # None: follow-ups are searched as they are


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, result: LLMResult) -> None:
        c = result.completion
        self.prompt_tokens += c.prompt_tokens or 0
        self.completion_tokens += c.completion_tokens or 0
        self.cost_usd += c.cost_usd or 0.0


class AskQuestion:
    def __init__(self, llm: Generator, search: Search, prompts: AssistantPrompts, tokenizer: Tokenizer, *,
                 context_budget: int) -> None:
        self._llm, self._search, self._prompts = llm, search, prompts
        self._tokenizer, self._budget = tokenizer, context_budget

    async def ask(self, question: str, *, groups: Sequence[str], country: str | None = None,
                  history: Sequence[Turn] = (), allow_clarification: bool = True, rid: str | None = None) -> Reply:
        """Answer one question. Raises LLMError when the answer step fails on every model."""
        with log_context(request_id=rid or uuid.uuid4().hex[:8]):
            started = time.perf_counter()
            logger.info("ask start", extra=kv(question_chars=len(question), groups=list(groups), country=country,
                                              history_turns=len(history)))
            logger.debug("question: %s", question)
            try:
                reply = await self._ask(question, groups, country, history, allow_clarification)
            except LLMError:
                logger.error("ask failed", extra=kv(ms=round((time.perf_counter() - started) * 1000)))
                raise
            logger.info("ask done", extra=kv(
                kind=reply.kind, found=reply.found, cited=len(reply.cited),
                invalid_citations=len(reply.invalid_citations), context_tokens=reply.context_tokens,
                model=reply.model_used, input_tokens=reply.prompt_tokens, output_tokens=reply.completion_tokens,
                cost=round(reply.cost_usd, 6), ms=round((time.perf_counter() - started) * 1000)))
            return reply

    async def _ask(self, question: str, groups: Sequence[str], country: str | None, history: Sequence[Turn],
                   allow_clarification: bool) -> Reply:
        usage = _Usage()
        intake = await self._intake(question, country, usage)
        language = intake.language if intake else None
        if intake and not intake.in_scope:
            logger.info("out of scope: no answer call")
            return _reply("out_of_scope", message(OUT_OF_SCOPE, language), usage, intake=intake)
        if intake and allow_clarification and intake.needs_clarification and intake.clarifying_question:
            logger.info("clarifying question instead of an answer")
            return _reply("clarification", intake.clarifying_question, usage, intake=intake)

        country = (intake.country if intake else None) or country   # named in the question > known profile
        query = await self._standalone(question, history, usage)
        hits = await asyncio.to_thread(self._search.search, query, groups, country)
        if not hits:
            logger.info("no readable chunk matches: not found, no answer call")
            return _reply("answer", message(NOT_FOUND, language), usage, found=False, query=query, intake=intake)
        context = build_context(hits, self._budget, self._tokenizer)
        result = await self._llm.generate(self._answer_messages(query, context, country), output_model=RagAnswer)
        usage.add(result)
        return self._answer_reply(result, context, hits, query, intake, language, usage, allow_clarification)

    def _answer_messages(self, query: str, context: Context, country: str | None) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self._prompts.answer}]
        if note := profile_note(country):
            messages.append({"role": "system", "content": note})
        messages.append({"role": "user", "content": f"<sources>\n{context.text}\n</sources>\n\nQuestion: {query}"})
        return messages

    def _answer_reply(self, result: LLMResult, context: Context, hits: list[Hit], query: str, intake: Intake | None,
                      language: str | None, usage: _Usage, allow_clarification: bool) -> Reply:
        answer: RagAnswer = result.parsed  # type: ignore[assignment]
        call = {"model_used": result.model_used, "fallback_failures": result.failures, "query": query,
                "finish_reason": result.completion.finish_reason, "retrieved": tuple(h.chunk.chunk_id for h in hits),
                "context_tokens": context.tokens, "intake": intake, "confidence": answer.confidence}
        if answer.needs_clarification and allow_clarification:
            logger.info("the answer model asked a clarifying question")
            return _reply("clarification", answer.answer, usage, **call)
        attr = attribute(answer.answer, answer.citations, context.sources)
        if attr.invalid:
            logger.warning("dropped citations of sources the model was not shown", extra=kv(invalid=list(attr.invalid)))
        if not (answer.found and attr.labels):
            text = MARKER.sub("", answer.answer).strip() if not answer.found else message(NOT_FOUND, language)
            return _reply("answer", text, usage, found=False, invalid_citations=attr.invalid, **call)
        if attr.uncited:
            logger.warning("statements without a source", extra=kv(uncited=attr.uncited, statements=attr.statements))
        cited = [context.sources[label] for label in attr.labels]
        logger.info("answer grounded", extra=kv(cited=[c.ref for c in cited], confidence=answer.confidence,
                                                statements=attr.statements, uncited=attr.uncited))
        return _reply("answer", attr.text, usage, found=True, cited=tuple(c.chunk_id for c in cited),
                      sources={c.chunk_id: c.text for c in cited}, invalid_citations=attr.invalid,
                      statements=attr.statements, uncited_statements=attr.uncited, **call)

    async def _intake(self, question: str, country: str | None, usage: _Usage) -> Intake | None:
        if self._prompts.intake is None:
            return None
        messages = [{"role": "system", "content": self._prompts.intake}]
        if note := profile_note(country):
            messages.append({"role": "system", "content": note})
        messages.append({"role": "user", "content": question})
        try:
            result = await self._llm.generate(messages, output_model=Intake)
        except LLMError as exc:  # intake is an optimisation: degrade to a plain answer
            logger.warning("intake failed, answering without it: %s", exc)
            return None
        usage.add(result)
        intake: Intake = result.parsed  # type: ignore[assignment]
        logger.info("intake", extra=kv(language=intake.language, in_scope=intake.in_scope, country=intake.country,
                                       needs_clarification=intake.needs_clarification))
        return intake

    async def _standalone(self, question: str, history: Sequence[Turn], usage: _Usage) -> str:
        """A follow-up rewritten without "it" / "that" (one model call); the question itself without history."""
        if not history or self._prompts.condense is None:
            return question
        dialog = "\n".join(f"User: {q}\nAssistant: {a}" for q, a in history)
        messages = [{"role": "system", "content": self._prompts.condense},
                    {"role": "user", "content": f"<dialog>\n{dialog}\n</dialog>\n\nFollow-up: {question}"}]
        try:
            result = await self._llm.generate(messages, output_model=StandaloneQuestion)
        except LLMError as exc:
            logger.warning("condense failed, searching the follow-up as it is: %s", exc)
            return question
        usage.add(result)
        standalone: StandaloneQuestion = result.parsed  # type: ignore[assignment]
        logger.info("follow-up condensed", extra=kv(chars=len(standalone.question)))
        logger.debug("standalone question: %s", standalone.question)
        return standalone.question


def _reply(kind: ReplyKind, text: str, usage: _Usage, **fields: object) -> Reply:
    return Reply(kind=kind, text=text, prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
                 cost_usd=usage.cost_usd, **fields)  # type: ignore[arg-type]
