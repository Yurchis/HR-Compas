"""The bot's reply to one question, and the fixed messages it uses when it does not call the answer model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from hr_compass.assistant.domain.intake import Intake

ReplyKind = Literal["answer", "clarification", "out_of_scope"]

OUT_OF_SCOPE = {
    "uk": "Я відповідаю лише на питання про роботу в компанії. З цим питанням звернися, будь ласка, до HR.",
    "ru": "Я отвечаю только на вопросы о работе в компании. С этим вопросом обратитесь, пожалуйста, в HR.",
    "en": "I only answer questions about working at the company. Please contact HR with this one.",
}
NOT_FOUND = {
    "uk": "Я не знайшов цього в документах, доступних тобі. Звернися, будь ласка, до HR.",
    "ru": "Я не нашёл этого в документах, доступных вам. Обратитесь, пожалуйста, в HR.",
    "en": "I could not find this in the documents available to you. Please contact HR.",
}


def message(table: Mapping[str, str], language: str | None) -> str:
    return table.get(language or "en", table["en"])


@dataclass(frozen=True, slots=True)
class Reply:
    kind: ReplyKind
    text: str
    found: bool | None = None                   # answers only: False = the bot abstained
    cited: tuple[str, ...] = ()                 # chunk_ids the answer relies on
    sources: Mapping[str, str] = field(default_factory=dict)   # cited chunk_id -> text (for groundedness)
    retrieved: tuple[str, ...] = ()             # chunk_ids the search returned
    invalid_citations: tuple[str, ...] = ()     # labels the model cited but was not shown
    statements: int = 0                         # found answers: statements in the text
    uncited_statements: int = 0                 # ... of them without a source marker
    confidence: str | None = None
    query: str = ""                             # the standalone question that was searched
    intake: Intake | None = None
    model_used: str | None = None
    fallback_failures: tuple[str, ...] = ()
    finish_reason: str | None = None
    context_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def as_result(self) -> dict[str, Any]:
        """The shape the answer scores take: {found, answer, cited, attributed}; attributed = every statement of a
        found answer names its source (None when nothing was found)."""
        return {"found": bool(self.found), "answer": self.text, "cited": list(self.cited),
                "attributed": (self.statements > 0 and self.uncited_statements == 0) if self.found else None}
