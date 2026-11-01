"""Async OpenRouter client: per-attempt timeout and retry with backoff (single model)."""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from types import TracebackType
from typing import Any, Self, TypeVar

import httpx
import truststore

from hr_compass.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class OpenRouterError(RuntimeError):
    """Non-retryable failure, or retries exhausted."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _UpstreamError(RuntimeError):
    """Malformed 2xx response or HTTP 200 carrying an `error`. Retryable unless `code` says otherwise."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Completion:
    """A single model response with usage accounting."""

    text: str
    model: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None

    def describe(self) -> str:
        return (
            f"input_tokens={self.prompt_tokens} output_tokens={self.completion_tokens} "
            f"cost={self.cost_usd} finish={self.finish_reason}"
        )


@dataclass(frozen=True, slots=True)
class Ranking:
    """Rerank response: document indices, most relevant first."""

    indices: tuple[int, ...]
    scores: tuple[float, ...]
    model: str
    tokens: int | None
    cost_usd: float | None

    def describe(self) -> str:
        top = f"{self.scores[0]:.3f}" if self.scores else "-"
        # A reranker only reads (query + documents): all its tokens are input tokens.
        return f"results={len(self.indices)} top_score={top} input_tokens={self.tokens} cost={self.cost_usd}"


class OpenRouterClient:
    """Use as an async context manager."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        headers = {"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"}
        if settings.app_url:
            headers["HTTP-Referer"] = settings.app_url
        if settings.app_title:
            headers["X-Title"] = settings.app_title
        t = settings.timeout
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=t.connect_s, read=t.read_s, write=t.write_s, pool=t.pool_s),
            transport=transport,
            # OS trust store, so corporate TLS-inspecting proxies (CA installed in Windows) work.
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        response_format: dict[str, Any] | None = None,
    ) -> Completion:
        s = self._s
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": s.generation.temperature,
            "top_p": s.generation.top_p,
            "max_tokens": s.generation.max_tokens,
            "usage": {"include": True},  # ask OpenRouter to report cost
        }
        if response_format is not None:
            payload["response_format"] = response_format
        logger.debug(
            "llm request model=%s messages=%d chars=%d structured=%s",
            model,
            len(messages),
            sum(len(m["content"]) for m in messages),
            response_format is not None,
        )
        return await self._request("llm", "/chat/completions", payload, model=model, parse=_parse)

    async def rerank(self, query: str, documents: list[str], *, model: str, top_n: int) -> Ranking:
        payload = {
            "model": model,
            "query": query,
            "documents": [{"text": d} for d in documents],
            "top_n": top_n,
        }
        logger.debug(
            "rerank request model=%s documents=%d chars=%d top_n=%d",
            model,
            len(documents),
            sum(map(len, documents)),
            top_n,
        )
        parse = partial(_parse_ranking, documents=len(documents))
        return await self._request("rerank", "/rerank", payload, model=model, parse=parse)

    async def _request(
        self,
        kind: str,
        path: str,
        payload: dict[str, Any],
        *,
        model: str,
        parse: Callable[[httpx.Response], T],
    ) -> T:
        """POST with per-attempt timeout and retries; `kind` prefixes the log lines (llm/rerank)."""
        s = self._s
        retry = s.retry
        last_error: Exception | None = None
        started = time.perf_counter()
        attempts = retry.max_retries + 1
        for attempt in range(attempts):
            retry_after: float | None = None
            attempt_started = time.perf_counter()
            try:
                async with asyncio.timeout(s.timeout.attempt_s):
                    response = await self._http.post(path, json=payload)
            except (TimeoutError, httpx.TransportError) as exc:  # httpx timeouts are TransportErrors
                last_error = exc
                logger.warning(
                    "%s attempt failed model=%s attempt=%d/%d error=%s %s",
                    kind, model, attempt + 1, attempts, type(exc).__name__, _timing(attempt_started, started),
                )
            else:
                status = response.status_code
                if status in retry.retry_statuses:
                    last_error = OpenRouterError(f"HTTP {status}: {_error_message(response)}", status_code=status)
                    retry_after = _retry_after(response) if retry.respect_retry_after else None
                    logger.warning(
                        "%s attempt failed model=%s attempt=%d/%d status=%d %s",
                        kind, model, attempt + 1, attempts, status, _timing(attempt_started, started),
                    )
                elif status >= 400:
                    logger.error(
                        "%s call rejected model=%s status=%d (no retry) attempt=%d/%d %s",
                        kind, model, status, attempt + 1, attempts, _timing(attempt_started, started),
                    )
                    raise OpenRouterError(f"HTTP {status}: {_error_message(response)}", status_code=status)
                else:
                    try:
                        result = parse(response)
                        logger.info(
                            "%s call ok model=%s attempt=%d/%d %s %s",
                            kind, model, attempt + 1, attempts, result.describe(), _timing(attempt_started, started),
                        )
                        return result
                    except _UpstreamError as exc:
                        if exc.code is not None and exc.code not in retry.retry_statuses:
                            logger.error(
                                "%s call rejected model=%s upstream code=%d (no retry) attempt=%d/%d %s",
                                kind, model, exc.code, attempt + 1, attempts, _timing(attempt_started, started),
                            )
                            raise OpenRouterError(str(exc), status_code=exc.code) from exc
                        last_error = OpenRouterError(str(exc), status_code=exc.code)
                        logger.warning(
                            "%s attempt failed model=%s attempt=%d/%d upstream glitch in 200 body: %s %s",
                            kind, model, attempt + 1, attempts, exc, _timing(attempt_started, started),
                        )

            if attempt < retry.max_retries:
                delay = retry.delay(attempt, random.random())  # noqa: S311 - jitter, not security
                if retry_after is not None:
                    delay = min(retry_after, retry.max_delay_s)
                await asyncio.sleep(delay)

        logger.error(
            "%s call failed model=%s after %d attempts total=%.2fs: %r",
            kind, model, attempts, time.perf_counter() - started, last_error,
        )
        raise OpenRouterError(
            f"gave up after {attempts} attempts: {last_error!r}",
            status_code=getattr(last_error, "status_code", None),
        ) from last_error


def _timing(attempt_started: float, started: float) -> str:
    # Attempt time is the HTTP round trip; total also counts earlier attempts and backoff sleeps.
    now = time.perf_counter()
    return f"attempt_time={now - attempt_started:.2f}s total={now - started:.2f}s"


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    try:
        return max(0.0, float(raw)) if raw else None
    except ValueError:
        return None


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return response.text[:200]
    if isinstance(error, dict):
        return str(error.get("message", error))[:200]
    return str(error or response.text)[:200]


def _body(response: httpx.Response) -> dict[str, Any]:
    # Anything malformed in a 2xx response is a provider glitch (truncated body, empty choices): retryable.
    try:
        body = response.json()
    except ValueError as exc:
        raise _UpstreamError("response is not valid JSON") from exc
    if not isinstance(body, dict):
        raise _UpstreamError(f"unexpected response shape: {str(body)[:200]}")
    if error := body.get("error"):
        code = error.get("code") if isinstance(error, dict) else None
        raise _UpstreamError(str(error)[:200], code=code if isinstance(code, int) else None)
    return body


def _parse(response: httpx.Response) -> Completion:
    body = _body(response)
    try:
        choice = body["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise _UpstreamError(f"unexpected response shape: {str(body)[:200]}") from exc
    usage = body.get("usage") or {}
    return Completion(
        text=text,
        model=body.get("model", ""),
        finish_reason=choice.get("finish_reason"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cost_usd=usage.get("cost"),
    )


def _parse_ranking(response: httpx.Response, *, documents: int) -> Ranking:
    body = _body(response)
    try:
        pairs = [(int(r["index"]), float(r["relevance_score"])) for r in body["results"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise _UpstreamError(f"unexpected rerank response shape: {str(body)[:200]}") from exc
    if not pairs or any(not 0 <= i < documents for i, _ in pairs):
        raise _UpstreamError(f"rerank returned no or out-of-range indices: {[i for i, _ in pairs]}")
    pairs.sort(key=lambda p: p[1], reverse=True)  # don't rely on the provider's ordering
    usage = body.get("usage") or {}
    return Ranking(
        indices=tuple(i for i, _ in pairs),
        scores=tuple(s for _, s in pairs),
        model=body.get("model", ""),
        tokens=usage.get("total_tokens"),
        cost_usd=usage.get("cost"),
    )
