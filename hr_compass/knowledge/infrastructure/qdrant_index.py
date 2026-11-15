"""Vector search: chunk vectors in an in-memory Qdrant collection, the access and country rules as a database filter.

The filter is applied by Qdrant, not asked of the model: a prompt like "do not show HR documents" is not
protection. A user without groups matches no chunk; a chunk with `access: []` is seen by nobody.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from qdrant_client import QdrantClient, models

from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Embedder, Hit, Query
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)

COLLECTION = "hr_compass"
UPSERT_BATCH = 256


def access_filter(groups: Iterable[str], country: str | None = None) -> models.Filter:
    """Chunks whose `access` shares a group with the user (never None: that would mean "no filter"); with a
    country, also only chunks of that country or company-wide ones (country is null)."""
    must: list = [models.FieldCondition(key="access", match=models.MatchAny(any=sorted(set(groups))))]
    if country is not None:
        must.append(models.Filter(should=[
            models.FieldCondition(key="country", match=models.MatchValue(value=country)),
            models.IsNullCondition(is_null=models.PayloadField(key="country")),
        ]))
    return models.Filter(must=must)


class QdrantRetriever:
    def __init__(self, chunks: list[ChunkRecord], embedder: Embedder, dim: int,
                 client: QdrantClient | None = None) -> None:
        self._embedder, self._client = embedder, client or QdrantClient(":memory:")
        self._build(chunks, dim)

    def _build(self, chunks: list[ChunkRecord], dim: int) -> None:
        started = time.perf_counter()
        vectors = self._embedder.embed([chunk.embedding_text() for chunk in chunks])
        if self._client.collection_exists(COLLECTION):
            self._client.delete_collection(COLLECTION)
        self._client.create_collection(
            COLLECTION, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
        for start in range(0, len(chunks), UPSERT_BATCH):
            self._client.upsert(COLLECTION, points=[
                models.PointStruct(id=i, vector=vectors[i], payload=chunks[i].to_dict())
                for i in range(start, min(start + UPSERT_BATCH, len(chunks)))])
        count = self.count()
        logger.info("vector index built", extra=kv(points=count, ms=round((time.perf_counter() - started) * 1000)))
        if count != len(chunks):
            raise RuntimeError(f"index has {count} points for {len(chunks)} chunks")

    def count(self, groups: Iterable[str] | None = None, country: str | None = None) -> int:
        flt = None if groups is None else access_filter(groups, country)
        return self._client.count(COLLECTION, count_filter=flt).count

    def search(self, query: Query) -> list[Hit]:
        vector = self._embedder.embed_query(query.text)
        points = self._client.query_points(COLLECTION, query=vector, limit=query.k,
                                           query_filter=access_filter(query.groups, query.country)).points
        return [Hit(ChunkRecord.from_dict(point.payload), point.score) for point in points]
