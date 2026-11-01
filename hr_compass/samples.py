"""Evaluation samples (golden set) stored as JSONL, one object per line."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


REPLY_KINDS = ("answer", "clarification", "out_of_scope")  # hr_compass.pipeline.ReplyKind


class SampleError(ValueError):
    """Raised when the samples file is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Sample:
    id: str
    question: str
    expected_answer: str | None = None
    expected_keywords: tuple[str, ...] = ()
    country: str | None = None  # employee profile, known before the question (None = unknown)
    sub_company: str | None = None
    expected_kind: str | None = None  # one of REPLY_KINDS; None = not checked


def load_samples(path: Path) -> list[Sample]:
    if not path.is_file():
        raise SampleError(f"samples file not found: {path}")
    samples: list[Sample] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
            sample = Sample(
                id=str(raw["id"]),
                question=raw["question"].strip(),
                expected_answer=raw.get("expected_answer"),
                expected_keywords=tuple(raw.get("expected_keywords", ())),
                country=raw.get("country"),
                sub_company=raw.get("sub_company"),
                expected_kind=raw.get("expected_kind"),
            )
        except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
            raise SampleError(f"{path}:{lineno}: invalid sample ({exc!r})") from exc
        if not sample.question:
            raise SampleError(f"{path}:{lineno}: empty question")
        if sample.expected_kind is not None and sample.expected_kind not in REPLY_KINDS:
            raise SampleError(
                f"{path}:{lineno}: expected_kind must be one of {', '.join(REPLY_KINDS)}, got {sample.expected_kind!r}"
            )
        if sample.id in seen:
            raise SampleError(f"{path}:{lineno}: duplicate id {sample.id!r}")
        seen.add(sample.id)
        samples.append(sample)
    if not samples:
        raise SampleError(f"{path}: no samples found")
    return samples
