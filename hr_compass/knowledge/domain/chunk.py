"""ChunkRecord: one indexed piece of a document and everything retrieval and evaluation need about it.

The shared kernel of three contexts: ingestion produces records, knowledge indexes and finds them, evaluation
checks answers against them. Stored as one JSON object per line in chunks.jsonl.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any

from hr_compass.shared.refs import chunk_ref

REQUIRED = ("chunk_id", "source", "title", "section", "access", "doc_hash", "chunk_index", "n_tokens", "text",
            "pipeline_version", "ingested_at")


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    chunk_id: str               # "<source>#<chunk_index>"
    source: str                 # path relative to the input folder
    title: str
    section: str                # heading path: "Section 2 > 2-5. Remote Work"
    access: tuple[str, ...]     # groups that may read it; () = nobody
    doc_hash: str               # content hash of the normalised document
    chunk_index: int
    n_tokens: int
    text: str
    pipeline_version: str
    ingested_at: str
    effective: str | None = None    # "Effective ..." date of the document, YYYY-MM-DD
    country: str | None = None      # None = company-wide

    @property
    def ref(self) -> str:
        """Log-safe id: the chunk_id carries the source path (names), the ref only a hash prefix."""
        return chunk_ref(self.doc_hash, self.chunk_index)

    def embedding_text(self) -> str:
        """What is embedded and keyword-indexed: the section path in front of the text (a contextual header)."""
        return f"{self.section}\n{self.text}" if self.section else self.text

    def with_access(self, access: Iterable[str]) -> ChunkRecord:
        return replace(self, access=tuple(access))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["access"] = list(self.access)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChunkRecord:
        missing = [key for key in REQUIRED if key not in data]
        if missing:
            raise ValueError(f"chunk record {data.get('chunk_id', '?')} misses {missing}")
        return cls(**{**{k: data[k] for k in REQUIRED}, "access": tuple(data["access"]),
                      "effective": data.get("effective"), "country": data.get("country")})
