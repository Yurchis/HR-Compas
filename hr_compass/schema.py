"""Structured answer contract the model must follow (Pattern 3)."""

from __future__ import annotations

import re
from typing import Any, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
ModelT = TypeVar("ModelT", bound=BaseModel)


class HRAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool = Field(description="True if the handbook contains the answer")
    answer: str = Field(min_length=1, description="Answer in the language of the question")
    sources: list[str] = Field(description="Handbook chunk ids used, e.g. ['3-3']")
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def _grounded(self) -> Self:
        if self.found and not self.sources:
            raise ValueError("found=true requires at least one source id")
        return self


class HRAnswerV3(HRAnswer):
    """v3: the model may ask a clarifying question instead of answering (e.g. the country is unknown)."""

    needs_clarification: bool = Field(
        description="True if `answer` is a clarifying question (e.g. which country) instead of an answer"
    )

    @model_validator(mode="after")
    def _clarification_has_no_answer(self) -> Self:
        if self.needs_clarification and (self.found or self.sources):
            raise ValueError("needs_clarification=true requires found=false and sources=[]")
        return self


# Answer schemas a prompt can declare in its first line: <!-- schema: hr_answer_v3 -->
OUTPUT_MODELS: dict[str, type[HRAnswer]] = {"hr_answer": HRAnswer, "hr_answer_v3": HRAnswerV3}


def response_format(schema_name: str, *, strict: bool, model: type[BaseModel] = HRAnswer) -> dict[str, Any]:
    """OpenRouter `response_format` payload for `model` (HRAnswer by default)."""
    return {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": strict, "schema": model.model_json_schema()},
    }


def parse_model(text: str, model: type[ModelT]) -> ModelT:
    """Parse and validate model output; tolerates a ```json fence. Raises ValueError on failure."""
    body = text.strip()
    if m := _FENCE.match(body):
        body = m.group(1)
    return model.model_validate_json(body)  # pydantic.ValidationError is a ValueError


def parse_answer(text: str) -> HRAnswer:
    return parse_model(text, HRAnswer)
