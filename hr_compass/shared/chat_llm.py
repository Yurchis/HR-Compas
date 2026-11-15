"""A synchronous chat model for the LLM judge: `chat(messages, schema) -> str` over the project's async
OpenRouterClient, so judge calls get the same retries, timeouts, logging and cost accounting as the bot.

    with ChatLLM(settings) as llm:
        reply = llm.chat([{"role": "user", "content": "..."}], schema=VERDICT_FORMAT)
        llm.cost()

It runs its own event loop: call it outside a running loop (after the bot's async part has finished).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from hr_compass.shared.openrouter import OpenRouterClient
from hr_compass.shared.settings import Settings


class ChatLLM:
    def __init__(self, settings: Settings, model: str | None = None, max_tokens: int = 500,
                 client: Any | None = None) -> None:
        self.model = model or settings.model
        self._settings = replace(settings, generation=replace(settings.generation, max_tokens=max_tokens))
        self._loop = asyncio.new_event_loop()
        self._client = client or OpenRouterClient(self._settings)
        self.calls, self.tokens_in, self.tokens_out, self.usd = 0, 0, 0, 0.0

    def chat(self, messages: list[dict], schema: dict | None = None) -> str:
        completion = self._loop.run_until_complete(
            self._client.complete(messages, model=self.model, response_format=schema))
        self.calls += 1
        self.tokens_in += completion.prompt_tokens or 0
        self.tokens_out += completion.completion_tokens or 0
        self.usd += completion.cost_usd or 0.0
        return completion.text

    def cost(self) -> float:
        """USD reported by OpenRouter for the calls so far."""
        return self.usd

    def close(self) -> None:
        if not self._loop.is_closed():
            self._loop.run_until_complete(self._client.__aexit__(None, None, None))
            self._loop.close()

    def __enter__(self) -> ChatLLM:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
