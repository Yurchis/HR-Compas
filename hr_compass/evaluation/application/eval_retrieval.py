"""Retrieval eval: recall@k / MRR of every search configuration on the testset, plus the access check."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hr_compass.evaluation.domain.retrieval_metrics import Search, check_access, evaluate, gate_metrics
from hr_compass.evaluation.domain.testset import EvalCase
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.retrieval import Hit, Query, Retriever
from hr_compass.shared.logging import kv

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    k: int
    questions: list[EvalCase]
    results: dict[str, dict[str, Any]]      # config -> recall, mrr, misses, ms, leaks, ranks, recall_by_kind
    access_leaks: dict[str, int]            # config -> chunks an ordinary employee got but may not read

    @property
    def access_ok(self) -> bool:
        return not any(self.access_leaks.values()) and not any(r["leaks"] for r in self.results.values())

    def gate_metrics(self) -> dict[str, Any]:
        return gate_metrics(self.results, self.questions, self.access_leaks)


def search_function(retriever: Retriever, policy: AccessPolicy, k: int) -> Search:
    """A configuration as the metrics call it: (question, user groups) -> hits, groups expanded by the policy."""
    def search(text: str, groups: Sequence[str]) -> list[Hit]:
        return retriever.search(Query(text, policy.expand(groups), k))
    return search


def run_retrieval_eval(configs: Mapping[str, Retriever], questions: list[EvalCase], policy: AccessPolicy,
                       k: int) -> RetrievalReport:
    searches = {name: search_function(retriever, policy, k) for name, retriever in configs.items()}
    results: dict[str, dict[str, Any]] = {}
    for name, search in searches.items():
        r = evaluate(search, questions, k, policy.can_read)
        by_kind: dict[str, list[bool]] = defaultdict(list)
        for q in questions:
            by_kind[q["kind"]].append(r["ranks"][q["id"]] is not None)
        r["recall_by_kind"] = {kind: sum(v) / len(v) for kind, v in sorted(by_kind.items())}
        results[name] = r
        logger.info("retrieval eval", extra=kv(config=name, recall=round(r["recall"], 3), mrr=round(r["mrr"], 3),
                                               leaks=r["leaks"], misses=r["misses"]))
    leaks = check_access(searches, questions, policy.can_read)
    logger.info("access check", extra=kv(leaks=leaks))
    return RetrievalReport(k, questions, results, leaks)
