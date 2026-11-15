"""SearchService: the one way the rest of the system searches. It expands the user's groups along the hierarchy,
builds the Query and logs every search (refs and scores, never texts or paths)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.retrieval import Hit, Query, Retriever
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, retriever: Retriever, policy: AccessPolicy, k: int, mode: str) -> None:
        self._retriever, self._policy, self.k, self.mode = retriever, policy, k, mode

    def query(self, text: str, groups: Iterable[str], country: str | None = None, k: int | None = None) -> Query:
        return Query(text, self._policy.expand(groups), k or self.k, country)

    def search(self, text: str, groups: Iterable[str], country: str | None = None, k: int | None = None) -> list[Hit]:
        query = self.query(text, groups, country, k)
        started = time.perf_counter()
        hits = self._retriever.search(query)
        logger.info("retrieval", extra=kv(
            mode=self.mode, query_chars=len(text), groups=sorted(query.groups), country=country, k=query.k,
            hits=[f"{h.chunk.ref}:{h.score:.3f}" for h in hits], ms=round((time.perf_counter() - started) * 1000)))
        logger.debug("retrieval query=%r chunk_ids=%s", text, [h.chunk.chunk_id for h in hits])
        return hits
