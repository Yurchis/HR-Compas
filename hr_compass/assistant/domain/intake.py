"""Intake: before answering, classify the question (language, scope, country) and decide whether to ask back."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Country = Literal["USA", "UA", "Costa Rica"]   # the country folders of the corpus ([ingest].countries)


class Intake(BaseModel):
    """Every field is required (nullable where unknown) so the JSON schema stays strict-friendly."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(description="ISO 639-1 code of the question language, e.g. 'uk', 'ru', 'en'")
    in_scope: bool = Field(description="True if the question is about the company, work, HR or benefits")
    country: Country | None = Field(description="Country of the employee if stated in the question, else null")
    needs_clarification: bool = Field(description="True if the answer depends on a fact the employee did not give")
    clarifying_question: str | None = Field(description="One short question in the employee's language, or null")


def profile_note(country: str | None) -> str | None:
    """A system note with the profile known before the question (e.g. from HR records); None if unknown."""
    if not country:
        return None
    return (f"Known employee profile (from HR records, not from the question): country={country}. "
            "Do not ask for it; it is already known.")
