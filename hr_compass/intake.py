"""Intake step: classify the employee's question before answering (language, scope, profile)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hr_compass.resilient import LLMResult, ResilientLLM

logger = logging.getLogger(__name__)

Country = Literal["USA", "UA", "Costa Rica"]
SubCompany = Literal["IT-Outsourcing", "IT-Product"]


class IntakeError(ValueError):
    """Raised when the intake prompt is missing or empty."""


class Intake(BaseModel):
    """Intake verdict. Every field is required (nullable where unknown) so the JSON schema stays strict-friendly."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(description="ISO 639-1 code of the question language, e.g. 'uk', 'ru', 'en'")
    in_scope: bool = Field(description="True if the question is about the company, work, HR or benefits")
    country: Country | None = Field(description="Country of the employee if stated in the question, else null")
    sub_company: SubCompany | None = Field(description="Subsidiary of the employee if stated, else null")
    needs_clarification: bool = Field(description="True if the answer depends on a fact the employee did not give")
    clarifying_question: str | None = Field(description="One short question in the employee's language, or null")


def load_intake_prompt(path: Path) -> str:
    if not path.is_file():
        raise IntakeError(f"intake prompt not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise IntakeError(f"intake prompt is empty: {path}")
    return text


def profile_note(country: str | None, sub_company: str | None) -> str | None:
    """System note with the employee profile known before the question (e.g. from HR records); None if unknown."""
    known = [f"country={country}"] * bool(country) + [f"sub_company={sub_company}"] * bool(sub_company)
    if not known:
        return None
    return (
        f"Known employee profile (from HR records, not from the question): {', '.join(known)}. "
        "Do not ask for these facts; they are already known."
    )


async def classify(
    llm: ResilientLLM,
    prompt: str,
    question: str,
    *,
    country: str | None = None,
    sub_company: str | None = None,
) -> tuple[Intake, LLMResult]:
    """Run the intake prompt; needs `structured_output.enabled` so the verdict is a validated `Intake`.

    A known profile (`country` / `sub_company`) is passed as a separate system note, so intake does not ask for it.
    """
    messages = [{"role": "system", "content": prompt}]
    if note := profile_note(country, sub_company):
        messages.append({"role": "system", "content": note})
    messages.append({"role": "user", "content": question})
    result = await llm.generate(messages, output_model=Intake)
    if not isinstance(result.parsed, Intake):
        raise IntakeError("intake needs [structured_output].enabled = true")
    verdict = result.parsed
    logger.info(
        "intake language=%s in_scope=%s country=%s sub_company=%s needs_clarification=%s "
        "input_tokens=%s output_tokens=%s",
        verdict.language,
        verdict.in_scope,
        verdict.country,
        verdict.sub_company,
        verdict.needs_clarification,
        result.completion.prompt_tokens,  # summed over repair attempts
        result.completion.completion_tokens,
    )
    return verdict, result
