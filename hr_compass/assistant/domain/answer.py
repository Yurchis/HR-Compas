"""What the answer model must return, and how its citations are checked against the sources it was shown.

The answer cites inline: every statement ends with the labels of its sources, "... 24 days [S1]." (prompt v6).
`attribute` checks those markers, renumbers them in the order the sources are listed to the user ([S3] -> [1]) and
counts the statements that cite nothing."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RagAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool = Field(description="True if the sources contain the answer")
    answer: str = Field(min_length=1, description="The answer, in the language of the question")
    citations: list[str] = Field(description="Labels of the sources used, e.g. ['S1', 'S3']")
    confidence: Literal["high", "medium", "low"]
    needs_clarification: bool = Field(description="True if `answer` is a clarifying question instead of an answer")

    @model_validator(mode="after")
    def _clarification_has_no_answer(self) -> Self:
        if self.needs_clarification and (self.found or self.citations):
            raise ValueError("needs_clarification=true requires found=false and citations=[]")
        return self


class StandaloneQuestion(BaseModel):
    """A follow-up rewritten so it can be understood without the dialog."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


def validate_citations(citations: list[str], labels: Collection[str]) -> tuple[list[str], list[str]]:
    """(valid, invalid) labels: "[S1]" and " S1 " count as "S1"; a label of a source the model was not shown is
    invalid and dropped, so an answer can never cite a chunk the user did not get."""
    cleaned = [c.strip().strip("[]").strip() for c in citations]
    valid = [c for c in dict.fromkeys(cleaned) if c in labels]
    invalid = [c for c in cleaned if c not in labels]
    return valid, invalid


MARKER = re.compile(r"\s*\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]")      # [S1] or [S1, S3]
LABEL = re.compile(r"S\d+")
# A statement ends at . ! ? … (not inside "1.5") or a line break; markers right after the stop belong to it.
STATEMENT_END = re.compile(r"(?<=[.!?…])(?:\s*\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\])*\s+|\n+")
MIN_STATEMENT_WORDS = 3   # "e.g." or a lone heading is not a statement


@dataclass(frozen=True, slots=True)
class Attribution:
    text: str                    # the answer with markers renumbered to the source list: [S3] -> [1]; unknown dropped
    labels: tuple[str, ...]      # the sources used, in the order they are listed: first inline use, then list-only
    invalid: tuple[str, ...]     # labels of sources the model was not shown (removed from text and list)
    statements: int              # statements in the answer
    uncited: int                 # statements without a valid marker


def attribute(answer: str, citations: list[str], labels: Collection[str]) -> Attribution:
    """Check the inline markers of an answer against the labels the model was shown and renumber them.
    A source named only in `citations` (no inline marker) still counts as used, listed after the inline ones."""
    inline = [label for m in MARKER.finditer(answer) for label in LABEL.findall(m.group(0))]
    listed, invalid_listed = validate_citations(citations, labels)
    used = [label for label in dict.fromkeys([*inline, *listed]) if label in labels]
    number = {label: i for i, label in enumerate(used, start=1)}

    def renumber(m: re.Match) -> str:
        kept = [str(number[label]) for label in LABEL.findall(m.group(0)) if label in number]
        return f" [{', '.join(kept)}]" if kept else ""

    text = answer.strip()
    pieces = STATEMENT_END.split(text)
    ends = [m.group(0) for m in STATEMENT_END.finditer(text)] + [""]   # holds the markers right after a stop
    statements = [piece + end for piece, end in zip(pieces, ends, strict=True)
                  if len(MARKER.sub("", piece).split()) >= MIN_STATEMENT_WORDS]
    cited = sum(1 for s in statements if any(label in number for label in LABEL.findall(
        "".join(m.group(0) for m in MARKER.finditer(s)))))
    invalid = tuple(dict.fromkeys([*(label for label in inline if label not in labels), *invalid_listed]))
    return Attribution(text=MARKER.sub(renumber, text).strip(), labels=tuple(used), invalid=invalid,
                       statements=len(statements), uncited=len(statements) - cited)
