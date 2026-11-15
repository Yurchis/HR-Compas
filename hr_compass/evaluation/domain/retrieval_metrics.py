"""Retrieval metrics: recall@k and MRR of a search configuration, the access check, and the flat numbers the
gate compares.

- `retrieval_questions`: the answerable cases with `relevant` resolved to chunk_ids; a quote that matches no chunk
  is an error, not a silent zero; no_answer cases have nothing to retrieve;
- `evaluate`: recall@k (a relevant chunk is in the top-k) and MRR (1 / rank of the first relevant chunk), plus
  ms/query and "leaks": hits the asking user may not read (must always be 0);
- `check_access`: every configuration, asked the access questions as an ordinary employee, returns nothing that
  employee may not read.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hr_compass.evaluation.domain.testset import ARCHIVE_MARKER, CanRead, Chunks, EvalCase, resolve
from hr_compass.knowledge.domain.retrieval import Hit

Search = Callable[[str, Sequence[str]], list[Hit]]   # (question, user groups) -> hits


class QuestionError(ValueError):
    """The testset does not match the chunks (a quote matches nothing, a duplicate id ...).
    `hr-compass eval lint` lists every such problem at once."""


def retrieval_questions(cases: list[EvalCase], chunks: Chunks, archive_marker: str = ARCHIVE_MARKER,
                        strict: bool = True) -> list[EvalCase]:
    """The answerable cases with `relevant` resolved to chunk_ids (non-archived chunks containing the quote).
    strict=False (comparing chunkings): a quote no chunk contains whole (cut by the chunking) is dropped, and a
    question left without relevant chunks counts as a miss instead of failing the run."""
    seen: set[str] = set()
    resolved = []
    for q in cases:
        if q["id"] in seen:
            raise QuestionError(f"duplicate question id {q['id']}")
        seen.add(q["id"])
        if not q.get("relevant"):
            continue   # no_answer: nothing to retrieve
        relevant: list[str] = []
        for spec in q["relevant"]:
            found = resolve(spec, chunks, archive_marker)
            if isinstance(spec, str):
                found = found if spec in chunks else []
            if not found and strict:
                what = spec if isinstance(spec, str) else f"quote {spec['quote']!r}"
                raise QuestionError(f"{q['id']}: {what} matches no chunk")
            relevant += [cid for cid in found if cid not in relevant]
        resolved.append({**q, "relevant": relevant})
    return resolved


def evaluate(search: Search, questions: list[EvalCase], k: int, can_read: CanRead) -> dict[str, Any]:
    """recall@k, MRR, the ids of the questions with no relevant chunk in the top-k, mean ms/query, leaks
    (hits the user may not read) and the rank of the first relevant chunk per question (None: a miss)."""
    found = reciprocal = leaks = context_tokens = 0
    total_ms = 0.0
    misses: list[str] = []
    ranks: dict[str, int | None] = {}
    for q in questions:
        started = time.perf_counter()
        hits = search(q["question"], q["groups"])[:k]
        total_ms += (time.perf_counter() - started) * 1000
        context_tokens += sum(hit.chunk.n_tokens for hit in hits)   # what the answer model would read
        relevant = set(q["relevant"])
        rank = next((i for i, hit in enumerate(hits, start=1) if hit.chunk.chunk_id in relevant), None)
        ranks[q["id"]] = rank
        if rank is None:
            misses.append(q["id"])
        else:
            found += 1
            reciprocal += 1 / rank
        leaks += sum(1 for hit in hits if not can_read(hit.chunk.access, q["groups"]))
    n = len(questions) or 1
    return {"recall": found / n, "mrr": reciprocal / n, "misses": misses, "ms": total_ms / n, "leaks": leaks,
            "context_tokens": context_tokens / n, "ranks": ranks}


def check_access(configs: Mapping[str, Search], questions: list[EvalCase], can_read: CanRead,
                 groups: Sequence[str] = ("all_employees",)) -> dict[str, int]:
    """Ask the access questions (the ones that need more groups) as a user with only `groups`, in every
    configuration; returns how many returned chunks that user may not read, per configuration (all 0: OK)."""
    probes = [q["question"] for q in questions if set(q["groups"]) - set(groups)]
    return {name: sum(1 for probe in probes for hit in search(probe, list(groups))
                      if not can_read(hit.chunk.access, groups))
            for name, search in configs.items()}


def gate_metrics(results: Mapping[str, Mapping[str, Any]], questions: list[EvalCase],
                 access_leaks: Mapping[str, int]) -> dict[str, Any]:
    """One run as flat numbers for `scores.gate`: "<config>/recall", "<config>/mrr", "<config>/leaks" (eval and
    access-check leaks), misses as "<config>:<question id>" and every such id under "cases". Time per query is
    left out: it measures the machine, not the search."""
    flat: dict[str, Any] = {}
    for name, r in results.items():
        flat[f"{name}/recall"], flat[f"{name}/mrr"] = r["recall"], r["mrr"]
        flat[f"{name}/leaks"] = r["leaks"] + access_leaks.get(name, 0)
    flat["failed"] = [f"{name}:{qid}" for name, r in results.items() for qid in r["misses"]]
    flat["cases"] = [f"{name}:{q['id']}" for name in results for q in questions]
    return flat


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))
