"""The result of a structured model call, shared by everything that calls a model through the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from hr_compass.shared.openrouter import Completion


class LLMError(RuntimeError):
    """Every model in the chain failed (or a non-fallbackable error occurred)."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


@dataclass(frozen=True, slots=True)
class LLMResult:
    completion: Completion          # usage summed over the repair attempts of the model that succeeded
    parsed: BaseModel               # the validated reply
    model_used: str
    failures: tuple[str, ...] = field(default_factory=tuple)  # models that failed before `model_used` answered

    @property
    def fallback_used(self) -> bool:
        return bool(self.failures)
