"""Resilient generation: structured output with validation and repair (Pattern 3) and model fallback (Pattern 4),
on top of the client's per-attempt timeout and retry with backoff (Patterns 1-2).

Every call asks for JSON by the given pydantic model; an invalid reply is sent back to the model with the
validation error (up to [structured_output].max_repair_attempts times), then the next model of the chain is tried.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any, TypeVar

from pydantic import BaseModel

from hr_compass.shared.llm import LLMError, LLMResult
from hr_compass.shared.openrouter import Completion, OpenRouterClient, OpenRouterError
from hr_compass.shared.settings import Settings

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
M = TypeVar("M", bound=BaseModel)


def schema_name(model: type[BaseModel]) -> str:
    """RagAnswer -> rag_answer."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", model.__name__).lower()


def response_format(model: type[BaseModel], *, strict: bool) -> dict[str, Any]:
    """OpenRouter `response_format` payload for `model`."""
    return {"type": "json_schema",
            "json_schema": {"name": schema_name(model), "strict": strict, "schema": model.model_json_schema()}}


def parse_model(text: str, model: type[M]) -> M:
    """Parse and validate model output; tolerates a ```json fence. Raises ValueError on failure."""
    body = text.strip()
    if m := _FENCE.match(body):
        body = m.group(1)
    return model.model_validate_json(body)  # pydantic.ValidationError is a ValueError


class _InvalidOutput(RuntimeError):
    pass


class ResilientLLM:
    def __init__(self, client: OpenRouterClient, settings: Settings) -> None:
        self._client = client
        self._s = settings

    async def generate(self, messages: list[dict[str, str]], *, output_model: type[BaseModel]) -> LLMResult:
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

    async def _try_model(self, model: str, messages: list[dict[str, str]],
                         output_model: type[BaseModel]) -> tuple[Completion, BaseModel]:
        so = self._s.structured_output
        fmt = response_format(output_model, strict=so.strict)
        convo = list(messages)
        total: Completion | None = None
        error = ""
        for attempt in range(so.max_repair_attempts + 1):
            if attempt:
                logger.info("%s: asking for a repaired structured reply (repair %d)", model, attempt)
            completion = await self._client.complete(convo, model=model, response_format=fmt)
            total = _accumulate(total, completion)
            try:
                return total, parse_model(completion.text, output_model)
            except ValueError as exc:
                error = str(exc)[:300]
                logger.info("%s: invalid structured output (%s)", model, error)
                convo += [
                    {"role": "assistant", "content": completion.text},
                    {"role": "user", "content": f"Your reply failed validation: {error}\n"
                                                "Reply again with ONLY a JSON object matching the required schema."},
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
