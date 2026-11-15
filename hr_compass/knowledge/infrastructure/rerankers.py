"""Rerankers (the Reranker port): a cross-encoder reads the query and each candidate together.

- CrossEncoderReranker: local, fastembed ONNX, ~80 MB, free; trained on English (MS MARCO);
- OpenRouterReranker: the OpenRouter /rerank endpoint (the project's client: retries, timeouts, cost logging).
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import cached_property
from pathlib import Path

from hr_compass.shared.logging import kv
from hr_compass.shared.openrouter import OpenRouterClient
from hr_compass.shared.settings import Settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self, model: str, models_dir: Path) -> None:
        self.model, self._models_dir = model, models_dir

    @cached_property
    def _encoder(self):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        started = time.perf_counter()
        encoder = TextCrossEncoder(self.model, cache_dir=str(self._models_dir))
        logger.info("reranker loaded", extra=kv(model=self.model, ms=round((time.perf_counter() - started) * 1000)))
        return encoder

    def scores(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._encoder.rerank(query, texts)] if texts else []


class OpenRouterReranker:
    """Synchronous over the async client: retrieval runs in a worker thread, so each call gets its own loop."""

    def __init__(self, settings: Settings, model: str) -> None:
        self._settings, self.model = settings, model

    def scores(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        return asyncio.run(self._scores(query, texts))

    async def _scores(self, query: str, texts: list[str]) -> list[float]:
        async with OpenRouterClient(self._settings) as client:
            ranking = await client.rerank(query, texts, model=self.model, top_n=len(texts))
        scores = [float("-inf")] * len(texts)   # a text the provider did not rank goes last
        for index, score in zip(ranking.indices, ranking.scores, strict=True):
            scores[index] = score
        return scores
