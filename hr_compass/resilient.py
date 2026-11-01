"""Resilient generation: structured output with validation/repair (Pattern 3) and model fallback (Pattern 4)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from hr_compass.config import Settings
from hr_compass.openrouter import Completion, OpenRouterClient, OpenRouterError
from pydantic import BaseModel

from hr_compass.schema import HRAnswer, parse_model, response_format

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Every model in the chain failed (or a non-fallbackable error occurred)."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


@dataclass(frozen=True, slots=True)
class LLMResult:
    completion: Completion  # usage is summed over repair attempts of the successful model
    parsed: BaseModel | None  # None when structured output is disabled (an HRAnswer unless `output_model` says otherwise)
    model_used: str
    failures: tuple[str, ...] = field(default_factory=tuple)  # failed models before success

    @property
    def fallback_used(self) -> bool:
        return bool(self.failures)


class _InvalidOutput(RuntimeError):
    pass


class ResilientLLM:
    def __init__(self, client: OpenRouterClient, settings: Settings) -> None:
        self._client = client
        self._s = settings

    async def generate(
        self, messages: list[dict[str, str]], *, output_model: type[BaseModel] = HRAnswer
    ) -> LLMResult:
        failures: list[str] = []
        for model in self._s.model_chain:
            try:
                completion, parsed = await self._try_model(model, messages, output_model)
            except OpenRouterError as exc:
                failures.append(f"{model}: {exc}")
                if exc.status_code in self._s.fallback.skip_statuses:
                    raise LLMError(failures) from exc
            except _InvalidOutput as exc:
                failures.append(f"{model}: {exc}")
            else:
                if failures:
                    logger.warning("fallback used: answered by %s after %d failed model(s)", model, len(failures))
                else:
                    logger.debug("answered by primary model %s", model)
                return LLMResult(completion, parsed, model, tuple(failures))
            logger.warning("model %s failed, %s", model, failures[-1])
        logger.error("all models failed: %s", "; ".join(failures))
        raise LLMError(failures)

    async def _try_model(
        self, model: str, messages: list[dict[str, str]], output_model: type[BaseModel]
    ) -> tuple[Completion, BaseModel | None]:
        so = self._s.structured_output
        fmt = response_format(so.schema_name, strict=so.strict, model=output_model) if so.enabled else None
        convo = list(messages)
        total: Completion | None = None
        error = ""
        for attempt in range(so.max_repair_attempts + 1 if so.enabled else 1):
            if attempt:
                logger.info("%s: asking for a repaired structured reply (repair %d)", model, attempt)
            completion = await self._client.complete(convo, model=model, response_format=fmt)
            total = _accumulate(total, completion)
            if not so.enabled:
                return total, None
            try:
                return total, parse_model(completion.text, output_model)
            except ValueError as exc:
                error = str(exc)[:300]
                logger.info("%s: invalid structured output (%s)", model, error)
                convo += [
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": f"Your reply failed validation: {error}\n"
                        "Reply again with ONLY a JSON object matching the required schema.",
                    },
                ]
        raise _InvalidOutput(f"invalid structured output after {so.max_repair_attempts + 1} attempt(s): {error}")


def _accumulate(total: Completion | None, new: Completion) -> Completion:
    if total is None:
        return new

    def add(a: float | int | None, b: float | int | None) -> float | int | None:
        return b if a is None else a if b is None else a + b

    return replace(
        new,
        prompt_tokens=add(total.prompt_tokens, new.prompt_tokens),
        completion_tokens=add(total.completion_tokens, new.completion_tokens),
        cost_usd=add(total.cost_usd, new.cost_usd),
    )
