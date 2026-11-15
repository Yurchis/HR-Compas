"""Retrieval language: a Query, the Hits it returns, and the ports search is built from.

A Query carries the user's groups already expanded by the AccessPolicy: every Retriever returns only chunks
those groups may read, and, when a country is known, only chunks of that country or company-wide ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Protocol

from hr_compass.knowledge.domain.chunk import ChunkRecord


@dataclass(frozen=True, slots=True)
class Query:
    text: str
    groups: frozenset[str]          # expanded: AccessPolicy.expand
    k: int = 5
    country: str | None = None      # None = any country

    def with_k(self, k: int) -> Query:
        return replace(self, k=k)

    def admits(self, chunk: ChunkRecord) -> bool:
        """The access and country rules every retriever applies."""
        readable = bool(set(chunk.access) & self.groups)
        return readable and (self.country is None or chunk.country in (None, self.country))


@dataclass(frozen=True, slots=True)
class Hit:
    chunk: ChunkRecord
    score: float

    def rescored(self, score: float) -> Hit:
        return replace(self, score=score)


class Retriever(Protocol):
    def search(self, query: Query) -> list[Hit]: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Document vectors, in input order (cached: every text is embedded once)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """The vector of one search query (not cached: queries rarely repeat and would only grow the cache)."""
        ...


class Reranker(Protocol):
    def scores(self, query: str, texts: list[str]) -> list[float]:
        """One relevance score per text, higher is better."""
        ...


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def rrf(rankings: list[list[Hit]], k: int, rrf_k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion: score = sum of 1 / (rrf_k + rank), rank starts at 1. Rankings from different
    searches have scores on different scales (cosine 0.5 vs BM25 13.0), so ranks are fused, not scores.
    A chunk found by several searches beats one found by a single search; ties keep first-seen order."""
    fused: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            seen = fused.get(hit.chunk.chunk_id)
            score = (seen.score if seen else 0.0) + 1 / (rrf_k + rank)
            fused[hit.chunk.chunk_id] = (seen or hit).rescored(score)
    return sorted(fused.values(), key=lambda hit: -hit.score)[:k]
