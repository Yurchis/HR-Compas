"""Retrievers composed of other retrievers: hybrid (RRF) and reranked. Both are Retrievers themselves, so the
four search configurations are plain objects, not lambdas."""

from __future__ import annotations

from hr_compass.knowledge.domain.retrieval import Hit, Query, Reranker, Retriever, rrf
from hr_compass.shared.settings import SearchConfig


class HybridRetriever:
    """The top `candidates` of every retriever, fused by rank (RRF)."""

    def __init__(self, retrievers: list[Retriever], candidates: int, rrf_k: int) -> None:
        self._retrievers, self._candidates, self._rrf_k = retrievers, candidates, rrf_k

    def search(self, query: Query) -> list[Hit]:
        rankings = [r.search(query.with_k(self._candidates)) for r in self._retrievers]
        return rrf(rankings, query.k, self._rrf_k)


class RerankingRetriever:
    """The top `candidates` of the inner retriever, re-ordered by a cross-encoder; score = its score."""

    def __init__(self, inner: Retriever, reranker: Reranker, candidates: int) -> None:
        self._inner, self._reranker, self._candidates = inner, reranker, candidates

    def search(self, query: Query) -> list[Hit]:
        candidates = self._inner.search(query.with_k(self._candidates))
        scores = self._reranker.scores(query.text, [h.chunk.embedding_text() for h in candidates])
        ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: -pair[1])
        return [hit.rescored(score) for hit, score in ranked[:query.k]]


def configurations(vector: Retriever, bm25: Retriever, reranker: Reranker,
                   config: SearchConfig) -> dict[str, Retriever]:
    """The four search configurations compared by the retrieval eval; [search].mode picks the one the bot uses."""
    hybrid = HybridRetriever([vector, bm25], config.candidates, config.rrf_k)
    return {"vector": vector, "bm25": bm25, "hybrid": hybrid,
            "hybrid+rerank": RerankingRetriever(hybrid, reranker, config.candidates)}
