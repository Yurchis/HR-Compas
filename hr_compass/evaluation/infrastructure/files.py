"""Evaluation files: the testset, the hand labels, and result files that say what produced them."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hr_compass.evaluation.domain.retrieval_metrics import QuestionError
from hr_compass.evaluation.domain.testset import EvalCase


def load_testset(path: Path) -> list[EvalCase]:
    """The cases; the file is a list or {"_comment": ..., "cases": [...]}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["cases"] if isinstance(data, Mapping) else data


class LabelError(QuestionError):
    """The hand-label file is not ready: an answer has no verdict yet."""


def load_labels(path: Path) -> list[dict[str, Any]]:
    """Answers labelled by people: [{id, case, answer, found, cited, correct, note, ...}]. Every "correct" must be
    true or false: an unlabelled answer (null) would silently count as "incorrect" and skew the agreement."""
    if not path.is_file():
        raise FileNotFoundError(f"no hand labels at {path}: label some bot answers first (see README, Evaluation)")
    items = json.loads(path.read_text(encoding="utf-8"))
    if missing := [it.get("id", "?") for it in items if not isinstance(it.get("correct"), bool)]:
        raise LabelError(f"{len(missing)} of {len(items)} answers in {path.name} have no verdict yet "
                         f"(set \"correct\" to true or false): {' '.join(missing)}")
    return items


def dataset_version(output_dir: Path) -> str | None:
    """The dataset_version of the ingested dataset the run used (manifest.json), None before the first ingest."""
    manifest = output_dir / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8")).get("dataset_version") if manifest.is_file() else None


def write_result(path: Path, payload: Mapping[str, Any], *, dataset: str | None, fingerprint: str) -> Path:
    """A result file that can be reproduced: the numbers plus the dataset version and the settings fingerprint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"created_at": datetime.now(UTC).isoformat(timespec="seconds"), "dataset_version": dataset,
            "settings_fingerprint": fingerprint}
    path.write_text(json.dumps({**meta, **payload}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
