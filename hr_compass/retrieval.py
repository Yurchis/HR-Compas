"""Retrieval: rerank handbook chunks by the question and keep the top N (instead of full context)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from hr_compass.config import RerankConfig
from hr_compass.knowledge import Chunk
from hr_compass.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Selection:
    chunks: list[Chunk]  # most relevant first; all input chunks when reranking was skipped or failed
    cost_usd: float = 0.0
    reranked: bool = False


class Reranker:
    def __init__(self, client: OpenRouterClient, config: RerankConfig) -> None:
        self._client = client
        self._c = config

    async def select(self, question: str, chunks: list[Chunk]) -> Selection:
        """Top-N chunks for the question. Reranking is an optimisation: on failure, return every chunk."""
        if len(chunks) <= self._c.top_n:
            logger.info("rerank skipped: %d chunk(s) <= top_n=%d", len(chunks), self._c.top_n)
            return Selection(list(chunks))
        started = time.perf_counter()
        try:
            ranking = await self._client.rerank(
                question, [c.render() for c in chunks], model=self._c.model, top_n=self._c.top_n
            )
        except OpenRouterError as exc:
            logger.warning(
                "rerank failed after %.2fs, using full context (%d chunks): %s",
                time.perf_counter() - started, len(chunks), exc,
            )
            return Selection(list(chunks))
        picked = [chunks[i] for i in ranking.indices[: self._c.top_n]]
        logger.info(
            "rerank selected %d/%d chunks=%s scores=%s total=%.2fs",
            len(picked),
            len(chunks),
            ",".join(c.id for c in picked),
            ",".join(f"{s:.3f}" for s in ranking.scores[: self._c.top_n]),
            time.perf_counter() - started,
        )
        return Selection(picked, cost_usd=ranking.cost_usd or 0.0, reranked=True)
