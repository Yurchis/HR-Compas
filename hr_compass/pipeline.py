"""Question -> reply pipeline: intake (language/scope/profile) -> context (full or reranked top-N) -> answer."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from hr_compass.intake import Intake, IntakeError, classify
from hr_compass.knowledge import Chunk, KnowledgeError, render_context, select_chunks
from hr_compass.logging_setup import request_id
from hr_compass.prompts import PromptTemplate
from hr_compass.resilient import LLMError, LLMResult, ResilientLLM
from hr_compass.retrieval import Reranker
from hr_compass.schema import HRAnswer, HRAnswerV3

logger = logging.getLogger(__name__)

OUT_OF_SCOPE = {
    "uk": "Я відповідаю лише на питання про роботу в компанії. З цим питанням звернися, будь ласка, до HR.",
    "ru": "Я отвечаю только на вопросы о работе в компании. С этим вопросом обратитесь, пожалуйста, в HR.",
    "en": "I only answer questions about working at the company. Please contact HR with this one.",
}

ReplyKind = Literal["answer", "clarification", "out_of_scope"]


@dataclass(frozen=True, slots=True)
class Reply:
    kind: ReplyKind
    text: str
    sources: tuple[str, ...] = ()
    confidence: str | None = None
    found: bool | None = None
    intake: Intake | None = None
    model_used: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: str | None = None  # of the answer call; None when no answer call was made
    fallback_failures: tuple[str, ...] = ()  # models that failed before `model_used` answered
    retrieved: tuple[str, ...] | None = None  # chunk ids picked by the reranker; None = full context


@dataclass(slots=True)
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, result: LLMResult) -> None:
        c = result.completion
        self.prompt_tokens += c.prompt_tokens or 0
        self.completion_tokens += c.completion_tokens or 0
        self.cost_usd += c.cost_usd or 0.0


class HRCompass:
    def __init__(
        self,
        llm: ResilientLLM,
        prompt: PromptTemplate,
        chunks: list[Chunk],
        *,
        intake_prompt: str | None,
        reranker: Reranker | None = None,
    ) -> None:
        self._llm = llm
        self._prompt = prompt
        self._chunks = chunks
        self._intake_prompt = intake_prompt  # None disables the intake step
        self._reranker = reranker  # None = full context
        self._system_cache: dict[tuple[str | None, str | None], str] = {}

    def _profile_chunks(self, country: str | None, sub_company: str | None) -> list[Chunk]:
        try:
            return select_chunks(self._chunks, country=country, sub_company=sub_company)
        except KnowledgeError:  # the handbook has nothing for this profile: fall back to all of it
            logger.info("no chunks for country=%s sub_company=%s, using the full handbook", country, sub_company)
            return self._chunks

    def _system_prompt(self, country: str | None, sub_company: str | None) -> str:
        key = (country, sub_company)
        if key not in self._system_cache:
            context = render_context(self._profile_chunks(country, sub_company))
            self._system_cache[key] = self._prompt.render(context=context)
            logger.info("context built country=%s sub_company=%s chars=%d", country, sub_company, len(context))
        return self._system_cache[key]

    async def _answer_prompt(
        self, question: str, country: str | None, sub_company: str | None, usage: _Usage
    ) -> tuple[str, tuple[str, ...] | None]:
        """System prompt for the answer call and the reranked chunk ids (None = full profile context)."""
        if self._reranker is None:
            return self._system_prompt(country, sub_company), None
        selection = await self._reranker.select(question, self._profile_chunks(country, sub_company))
        usage.cost_usd += selection.cost_usd
        context = render_context(selection.chunks)
        logger.info(
            "context built country=%s sub_company=%s chars=%d reranked=%s",
            country, sub_company, len(context), selection.reranked,
        )
        retrieved = tuple(c.id for c in selection.chunks) if selection.reranked else None
        return self._prompt.render(context=context), retrieved

    async def ask(
        self,
        question: str,
        *,
        allow_clarification: bool = True,
        country: str | None = None,
        sub_company: str | None = None,
        rid: str | None = None,
    ) -> Reply:
        """Answer one question. Raises LLMError when the answer step fails on every model.

        `country` / `sub_company` — the employee profile when it is already known (e.g. from the golden set);
        a country or sub-company named in the question itself (found by intake) takes precedence.
        `rid` — request id for the log lines (default: a random one).
        """
        token = request_id.set(rid or uuid.uuid4().hex[:8])
        started = time.perf_counter()
        # Question text is user data: only its size at INFO, the text itself at DEBUG.
        logger.info(
            "ask start question_chars=%d intake=%s profile_country=%s profile_sub_company=%s",
            len(question), self._intake_prompt is not None, country, sub_company,
        )
        logger.debug("question: %s", question)
        try:
            reply = await self._ask(
                question, allow_clarification=allow_clarification, country=country, sub_company=sub_company
            )
            logger.info(
                "ask done kind=%s found=%s sources=%s confidence=%s model=%s input_tokens=%d output_tokens=%d "
                "cost=$%.6f total=%.2fs",
                reply.kind,
                reply.found,
                ",".join(reply.sources) or "-",
                reply.confidence,
                reply.model_used,
                reply.prompt_tokens,
                reply.completion_tokens,
                reply.cost_usd,
                time.perf_counter() - started,
            )
            return reply
        except LLMError:
            logger.error("ask failed after %.2fs", time.perf_counter() - started)
            raise
        finally:
            request_id.reset(token)

    async def _ask(
        self, question: str, *, allow_clarification: bool, country: str | None, sub_company: str | None
    ) -> Reply:
        usage = _Usage()
        intake = await self._intake(question, usage, country=country, sub_company=sub_company)

        if intake and not intake.in_scope:
            logger.info("question is out of scope, skipping the answer call")
            text = OUT_OF_SCOPE.get(intake.language, OUT_OF_SCOPE["en"])
            return self._reply("out_of_scope", text, usage, intake=intake)
        if intake and allow_clarification and intake.needs_clarification and intake.clarifying_question:
            logger.info("asking a clarifying question instead of answering")
            return self._reply("clarification", intake.clarifying_question, usage, intake=intake)

        # Named in the question > known profile.
        country = (intake.country if intake else None) or country
        sub_company = (intake.sub_company if intake else None) or sub_company
        system, retrieved = await self._answer_prompt(question, country, sub_company, usage)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        result = await self._llm.generate(messages, output_model=self._prompt.output_model)
        usage.add(result)

        call = {
            "intake": intake,
            "model_used": result.model_used,
            "finish_reason": result.completion.finish_reason,
            "fallback_failures": result.failures,
            "retrieved": retrieved,
        }
        parsed = result.parsed
        if isinstance(parsed, HRAnswerV3) and parsed.needs_clarification and allow_clarification:
            # v3+ prompts: the answer model itself asks (e.g. which country) instead of guessing.
            logger.info("answer model asked a clarifying question instead of answering")
            return self._reply("clarification", parsed.answer, usage, **call)
        if isinstance(parsed, HRAnswer):
            return self._reply(
                "answer",
                parsed.answer,
                usage,
                sources=tuple(parsed.sources),
                confidence=parsed.confidence,
                found=parsed.found,
                **call,
            )
        return self._reply("answer", result.completion.text, usage, **call)

    async def _intake(
        self, question: str, usage: _Usage, *, country: str | None = None, sub_company: str | None = None
    ) -> Intake | None:
        if self._intake_prompt is None:
            return None
        try:
            intake, result = await classify(
                self._llm, self._intake_prompt, question, country=country, sub_company=sub_company
            )
        except (LLMError, IntakeError) as exc:  # intake is an optimisation: degrade to a plain answer
            logger.warning("intake failed, answering without it: %s", exc)
            return None
        usage.add(result)
        return intake

    @staticmethod
    def _reply(kind: ReplyKind, text: str, usage: _Usage, **fields: object) -> Reply:
        return Reply(
            kind=kind,
            text=text,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            **fields,  # type: ignore[arg-type]
        )
