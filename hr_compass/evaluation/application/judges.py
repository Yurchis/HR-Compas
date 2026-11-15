"""The LLM judge: correctness against the reference, groundedness against the cited sources."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from hr_compass.evaluation.domain.judging import (
    CLAIMS_FORMAT,
    VERDICT_FORMAT,
    ChatModel,
    Verdict,
    correctness_messages,
    groundedness_messages,
    parse_claims,
    parse_verdict,
)
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


class LlmJudge:
    def __init__(self, llm: ChatModel, correct_prompt: str, grounded_prompt: str) -> None:
        self._llm, self._correct_prompt, self._grounded_prompt = llm, correct_prompt, grounded_prompt

    def correct(self, case: Mapping[str, Any], answer: str) -> Verdict:
        """Is `answer` correct against the case's reference? One call."""
        reply = self._llm.chat(correctness_messages(self._correct_prompt, case, answer), schema=VERDICT_FORMAT)
        verdict = parse_verdict(reply, case.get("id"))
        logger.info("judge", extra=kv(case=case.get("id"), verdict=verdict.verdict))
        logger.debug("judge case=%s reason: %s", case.get("id"), verdict.reason)
        return verdict

    def grounded(self, answer: str, found: bool, sources: list[str]) -> tuple[bool | None, list[str]]:
        """(all claims supported, [unsupported claims]); a not-found answer claims nothing: (None, []) without
        a model call. `sources` = texts of the chunks the answer cites."""
        if not found:
            return None, []
        claims = parse_claims(self._llm.chat(groundedness_messages(self._grounded_prompt, sources, answer),
                                             schema=CLAIMS_FORMAT))
        unsupported = [c.claim for c in claims if not c.supported]
        logger.info("grounded", extra=kv(claims=len(claims), unsupported=len(unsupported), sources=len(sources)))
        logger.debug("unsupported claims: %s", unsupported)
        return not unsupported, unsupported
