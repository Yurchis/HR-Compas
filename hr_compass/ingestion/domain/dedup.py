"""Deduplication.

- exact: `content_hash` - the same content gives the same hash, whatever the line endings or spacing;
- near: `near_duplicates` - pairs of documents whose word 5-shingles overlap above NEAR_DUP_JACCARD
  (versions of one policy, one template filled in for different people). Every pair is compared once:
  O(n^2) is fine for a folder; for millions of documents use MinHash + LSH.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from itertools import combinations

from hr_compass.ingestion.domain.normalize import ZERO_WIDTH

logger = logging.getLogger(__name__)

SHINGLE_WORDS = 5
NEAR_DUP_JACCARD = 0.8      # shingle overlap above which two documents are near-duplicates


def canonical(text: str) -> str:
    """The form that is hashed: one Unicode form (NFKC), no invisible characters, every run of
    whitespace (spaces, tabs, line endings, blank lines, page breaks) as one space, no outer spaces.
    Case and punctuation are content, so they are kept."""
    text = ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))
    return re.sub(r"\s+", " ", text).strip()


def content_hash(text: str) -> str:
    """sha256 (hex) of the canonical form of the text."""
    return hashlib.sha256(canonical(text).encode("utf-8")).hexdigest()


def shingles(text: str, k: int = SHINGLE_WORDS) -> set[tuple[str, ...]]:
    """Every run of k consecutive words (case-folded, punctuation and markup ignored).
    A text shorter than k words is one shingle; a text without words has none."""
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
    if not words:
        return set()
    return {tuple(words[i:i + k]) for i in range(max(1, len(words) - k + 1))}


def jaccard(a: set, b: set) -> float:
    """|a & b| / |a | b|; 0.0 for two empty sets (nothing in common to speak of)."""
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def near_duplicates(docs: Mapping[str, str] | Iterable[tuple[str, str]], threshold: float = NEAR_DUP_JACCARD,
                    k: int = SHINGLE_WORDS) -> list[tuple[str, str, float]]:
    """Pairs (id_a, id_b, jaccard) of documents whose shingle sets overlap at least `threshold`,
    most similar first. Each pair is compared once; ids keep their input order within a pair."""
    items = list(docs.items() if isinstance(docs, Mapping) else docs)
    sets = [(doc_id, shingles(text, k)) for doc_id, text in items]
    pairs = []
    compared = skipped = 0
    for (id_a, a), (id_b, b) in combinations(sets, 2):
        if not a or not b or min(len(a), len(b)) / max(len(a), len(b)) < threshold:
            skipped += 1
            continue  # jaccard <= |small| / |large|: this pair cannot reach the threshold
        compared += 1
        score = jaccard(a, b)
        if score >= threshold:
            pairs.append((id_a, id_b, score))
    logger.debug("near_duplicates: docs=%d pairs compared=%d skipped by size bound=%d found=%d (k=%d, threshold=%s)",
                 len(sets), compared, skipped, len(pairs), k, threshold)
    return sorted(pairs, key=lambda p: -p[2])
