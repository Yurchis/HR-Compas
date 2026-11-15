"""The RAG testset: one golden set for retrieval metrics and answer evals, and `lint` that tests it.

A case (data/testset.json):

    {"id": "q01", "kind": "paraphrase", "groups": ["all_employees"],
     "question": "How many days a week can I work from home?",
     "relevant": [{"source": "Handbook (US) 2026.docx", "quote": "one day per week"}],
     "must": [["one day", "1 day"], ["two days", "2 days"]],
     "reference": "One day a week for 0-3 years of service, two days after 3 years."}

- `relevant`: the chunks that answer it, as a quote (+ optionally the end of the source path) or a chunk_id;
  quotes survive re-chunking and are resolved against the chunk records;
- `must`: facts the answer must contain: every group needs one of its options (after `norm`). Options in other
  languages are fine; at least one option of each group must be in the relevant chunks, or the fact is not
  from the documents;
- `kind`: paraphrase, exact, cross-lingual, access, stale (an archived copy says otherwise; asked as hr, the only
  group that can read the archive), no_answer (the documents do not say: the bot must abstain; no `must`, no
  `relevant`).

Archived copies are never relevant: an answer from an outdated handbook is a wrong answer.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NotRequired, TypedDict

from hr_compass.knowledge.domain.chunk import ChunkRecord

KINDS_MIN = 2
ARCHIVE_MARKER = "/Archive/"
REQUIRED = ("id", "kind", "groups", "question", "reference")

Chunks = Mapping[str, "ChunkRecord | str"]          # chunk_id -> record (or just its text, in small tests)
CanRead = Callable[[Iterable[str], Iterable[str]], bool]   # (chunk access, user groups) -> readable?


class EvalCase(TypedDict):
    id: str
    kind: str
    groups: list[str]
    question: str
    reference: str
    relevant: NotRequired[list[Any]]     # quotes {"quote", "source"?} or chunk_ids; chunk_ids after resolve_cases
    must: NotRequired[list[list[str]]]


def norm(text: str) -> str:
    """Lower case, one kind of minus and space: '−15 °C' and '-15  °c' compare equal."""
    text = text.lower().replace("−", "-").replace("–", "-").replace("—", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _plain_can_read(access: Iterable[str], groups: Iterable[str]) -> bool:
    return bool(set(access) & set(groups))


def _text(chunk: ChunkRecord | str) -> str:
    return chunk.text if isinstance(chunk, ChunkRecord) else chunk


def _source(chunk_id: str) -> str:
    return chunk_id.rsplit("#", 1)[0]


def resolve(spec: str | Mapping[str, str], chunks: Chunks, archive_marker: str = ARCHIVE_MARKER) -> list[str]:
    """chunk_ids for one `relevant` entry: a chunk_id as is (checked by `lint`), a quote -> every non-archived
    chunk containing it (whose source ends with `source`, when given)."""
    if isinstance(spec, str):
        return [spec]
    quote, source = norm(spec["quote"]), spec.get("source", "")
    return [cid for cid, chunk in chunks.items()
            if archive_marker not in cid and _source(cid).endswith(source) and quote in norm(_text(chunk))]


def relevant_ids(case: Mapping[str, Any], chunks: Chunks, archive_marker: str = ARCHIVE_MARKER) -> list[str]:
    ids: list[str] = []
    for spec in case.get("relevant", []):
        ids += [cid for cid in resolve(spec, chunks, archive_marker) if cid not in ids]
    return ids


def resolve_cases(cases: list[EvalCase], chunks: Chunks, archive_marker: str = ARCHIVE_MARKER) -> list[EvalCase]:
    """Copies of the cases with `relevant` as chunk_ids (what scoring and retrieval metrics compare with).
    Run `lint` first: an unresolvable quote silently becomes an empty list here."""
    return [{**case, "relevant": relevant_ids(case, chunks, archive_marker)} for case in cases]


def lint(cases: list[EvalCase], chunks: Chunks, *, kinds_min: int = KINDS_MIN, archive_marker: str = ARCHIVE_MARKER,
         can_read: CanRead = _plain_can_read) -> list[str]:
    """Problems of the testset, one human-readable string each, e.g. "q07: unknown chunk id x#9".

    Reported: missing fields, duplicate ids, unknown chunk ids, quotes that match no chunk, archived relevant
    chunks, relevant chunks the case's groups may not read (`can_read`, records only), answerable cases without
    `relevant` or `must`, `must` facts not found in the relevant chunks, no_answer cases with `must` or
    `relevant`, kinds with fewer than `kinds_min` cases. See also `reference_problems`."""
    problems: list[str] = []
    seen: set[str] = set()
    for n, case in enumerate(cases, start=1):
        cid = case.get("id") or f"case #{n}"
        problems += [f"{cid}: missing field {name!r}" for name in REQUIRED if not case.get(name)]
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        problems += _case_problems(cid, case, chunks, archive_marker, can_read)
    for kind, count in sorted(Counter(c.get("kind") for c in cases).items(), key=lambda kv: str(kv[0])):
        if count < kinds_min:
            problems.append(f"kind {kind}: {count} case(s), needs at least {kinds_min}")
    return problems


def _case_problems(cid: str, case: Mapping[str, Any], chunks: Chunks, archive_marker: str,
                   can_read: CanRead) -> list[str]:
    must, relevant = case.get("must") or [], case.get("relevant") or []
    if case.get("kind") == "no_answer":
        return [f"{cid}: a no_answer case must have no `must` and no `relevant`"] if must or relevant else []
    problems = []
    if not relevant:
        problems.append(f"{cid}: no `relevant` chunks for an answerable case")
    if not must:
        problems.append(f"{cid}: no `must` facts for an answerable case")
    ids: list[str] = []
    for spec in relevant:
        if isinstance(spec, str) and spec not in chunks:
            problems.append(f"{cid}: unknown chunk id {spec}")
            continue
        found = resolve(spec, chunks, archive_marker)
        if not found:
            where = f" in *{spec['source']}" if spec.get("source") else ""
            problems.append(f"{cid}: quote {spec['quote']!r} matches no chunk{where}")
        ids += [i for i in found if i not in ids]
    groups = case.get("groups") or []
    for i in ids:
        if archive_marker in i:
            problems.append(f"{cid}: relevant chunk {i} is an archived copy")
        record = chunks[i]
        if isinstance(record, ChunkRecord) and not can_read(record.access, groups):
            problems.append(f"{cid}: relevant chunk {i} is not readable by groups {sorted(groups)}")
    if ids:
        evidence = norm(" ".join(_text(chunks[i]) for i in ids))
        problems += [f"{cid}: `must` fact {group} not found in the relevant chunks"
                     for group in must if not any(norm(option) in evidence for option in group)]
    return problems


def reference_problems(cases: list[EvalCase]) -> list[str]:
    """`must` facts missing from the case's own reference answer: the perfect answer would fail its own test,
    so no answer can ever pass. Kept out of `lint` (the lesson's check 1 has such a case on purpose)."""
    problems = []
    for case in cases:
        reference = norm(case.get("reference") or "")
        for group in case.get("must") or []:
            if reference and not any(norm(option) in reference for option in group):
                problems.append(f"{case.get('id')}: `must` fact {group} not found in the reference answer")
    return problems
