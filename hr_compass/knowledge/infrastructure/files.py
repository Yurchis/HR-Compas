"""Reading the dataset: chunk records (chunks.jsonl) and access rules (config/access.json)."""

from __future__ import annotations

import json
from pathlib import Path

from hr_compass.knowledge.domain.chunk import ChunkRecord

CHUNKS_FILE = "chunks.jsonl"


def load_chunks(path: Path) -> list[ChunkRecord]:
    """All records of a chunks.jsonl file (or of `<dir>/chunks.jsonl`), in file order."""
    path = path / CHUNKS_FILE if path.is_dir() else path
    if not path.is_file():
        raise FileNotFoundError(f"no chunks at {path}: run `hr-compass ingest` first")
    return [ChunkRecord.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_access_rules(path: Path) -> dict[str, tuple[str, ...]]:
    """{rule: groups}; keys starting with "_" are comments."""
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: tuple(v) for k, v in rules.items() if not k.startswith("_")}
