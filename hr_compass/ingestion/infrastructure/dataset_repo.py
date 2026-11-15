"""The ingested dataset on disk (`[ingest].output_dir`):

    chunks.jsonl     one ChunkRecord per line, what the index is built from
    <source>.md      the normalised text of each document (same folder layout as the input)
    manifest.json    dataset_version, pipeline version, extraction settings, every file's hashes and status
    _report.json     the same per-file report, for people
    audit.jsonl      append-only lineage: what happened to each file in each run; never rotated

Source paths hold people's names: these files are git-ignored (data/data_clean/).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.infrastructure.files import CHUNKS_FILE

PAGE_BREAK = "\n\n---\n\n"   # how a PDF page break (\f) is written into the .md file


class DatasetRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load_previous(self) -> tuple[dict[str, Any], dict[str, list[ChunkRecord]]]:
        """(manifest, {source: records}) of the last run; empty when there was none."""
        manifest_path, chunks_path = self.root / "manifest.json", self.root / CHUNKS_FILE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        chunks: dict[str, list[ChunkRecord]] = {}
        if chunks_path.exists():
            for line in chunks_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = ChunkRecord.from_dict(json.loads(line))
                    chunks.setdefault(record.source, []).append(record)
        return manifest, chunks

    def _text_path(self, source: str) -> Path:
        return self.root / f"{source}.md"

    def has_text(self, source: str) -> bool:
        return self._text_path(source).exists()

    def read_text(self, source: str) -> str:
        return self._text_path(source).read_text(encoding="utf-8").rstrip("\n")

    def write_text(self, source: str, text: str) -> None:
        path = self._text_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("\f", PAGE_BREAK) + "\n", encoding="utf-8")

    def text_sources(self) -> list[str]:
        """The source of every stored .md text, including texts no manifest knows about any more."""
        if not self.root.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix()[:-len(".md")] for p in self.root.rglob("*.md"))

    def remove_text(self, source: str) -> bool:
        path = self._text_path(source)
        if path.exists():
            path.unlink()
            return True
        return False

    def audit(self, event: str, source: str, **extra: Any) -> dict[str, Any]:
        """Append one event ({ts, event, source, **extra}) to audit.jsonl; returns the event."""
        entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, "source": source,
                 **extra}
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def save(self, manifest: dict[str, Any], records: list[ChunkRecord]) -> None:
        """chunks.jsonl, manifest.json and _report.json (= manifest["files"])."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "_report.json").write_text(json.dumps(manifest["files"], ensure_ascii=False, indent=2),
                                                encoding="utf-8")
        with (self.root / CHUNKS_FILE).open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        (self.root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
