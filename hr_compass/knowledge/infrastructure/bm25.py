"""Keyword search (BM25) over the same text as the embeddings: finds exact codes and names ("DB-450") that
vectors blur."""

from __future__ import annotations

import logging
import time

from rank_bm25 import BM25Okapi

from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Hit, Query, tokenize
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


class Bm25Retriever:
    def __init__(self, chunks: list[ChunkRecord]) -> None:
        started = time.perf_counter()
        self._chunks = chunks
        self._bm25 = BM25Okapi([tokenize(c.embedding_text()) for c in chunks]) if chunks else None
        logger.info("bm25 index built", extra=kv(chunks=len(chunks), ms=round((time.perf_counter() - started) * 1000)))

    def search(self, query: Query) -> list[Hit]:
        """Top-k by BM25; chunks without a single query word and chunks the query does not admit are skipped."""
        terms = tokenize(query.text)
        if self._bm25 is None or not terms:
            return []
        scores = self._bm25.get_scores(terms)
        ranked = sorted((i for i, s in enumerate(scores) if s > 0 and query.admits(self._chunks[i])),
                        key=lambda i: -scores[i])
        return [Hit(self._chunks[i], float(scores[i])) for i in ranked[:query.k]]
