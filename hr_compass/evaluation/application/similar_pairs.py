"""Semantic near-duplicates: the most similar chunk pairs from different documents (cosine of embeddings).

Pairs the ingestion tools already catch are skipped: identical text (content hash) and near-copies (word 5-shingle
Jaccard >= max_jaccard). What is left says the same thing in other words.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from hr_compass.ingestion.domain.dedup import NEAR_DUP_JACCARD, content_hash, jaccard, shingles
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Embedder
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


def similar_pairs(chunks: list[ChunkRecord], embedder: Embedder, top: int = 5,
                  max_jaccard: float = NEAR_DUP_JACCARD) -> list[tuple[float, str, str]]:
    """(cosine, chunk_id_a, chunk_id_b), most similar first. Vectors are normalised first: this model's are not,
    so a plain dot product is not a cosine."""
    n = len(chunks)
    if n < 2:
        return []
    started = time.perf_counter()
    vectors = np.asarray(embedder.embed([c.embedding_text() for c in chunks]), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    scores = vectors @ vectors.T
    source = np.unique([c.source for c in chunks], return_inverse=True)[1]
    text = np.unique([content_hash(c.text) for c in chunks], return_inverse=True)[1]
    valid = np.triu(np.ones_like(scores, dtype=bool), k=1)                  # each pair once, no self-pairs
    valid &= source[:, None] != source[None, :]                             # different documents
    valid &= text[:, None] != text[None, :]                                 # not an exact duplicate
    scores = np.where(valid, scores, -np.inf)

    shingle_sets: dict[int, set] = {}

    def words(i: int) -> set:
        if i not in shingle_sets:
            shingle_sets[i] = shingles(chunks[i].text)
        return shingle_sets[i]

    pairs: list[tuple[float, str, str]] = []
    skipped = 0
    for flat in np.argsort(scores, axis=None)[::-1]:
        score = scores.flat[flat]
        if not np.isfinite(score) or len(pairs) == top:
            break
        a, b = divmod(int(flat), n)
        if jaccard(words(a), words(b)) >= max_jaccard:
            skipped += 1   # a near-copy: the shingles of ingestion find it already
            continue
        pairs.append((float(score), chunks[a].chunk_id, chunks[b].chunk_id))
    logger.info("similar pairs", extra=kv(chunks=n, candidates=int(valid.sum()), near_copies_skipped=skipped,
                                          top=len(pairs), ms=round((time.perf_counter() - started) * 1000)))
    return pairs
