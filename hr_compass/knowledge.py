"""Knowledge base: handbook chunks from `data/raw/*.json` rendered as prompt context."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeError(ValueError):
    """Raised when a chunk file is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    title: str
    section: str
    country: str
    sub_company: tuple[str, ...]
    applies_to: tuple[str, ...]
    paid_status: str
    eligibility: str | None
    text: str

    def render(self) -> str:
        meta = [
            f"country: {self.country}",
            f"sub_company: {', '.join(self.sub_company)}",
            f"applies_to: {', '.join(self.applies_to)}",
            f"paid: {self.paid_status}",
        ]
        if self.eligibility:
            meta.append(f"eligibility: {self.eligibility}")
        header = f"[{self.id}] {self.title} ({self.section}) | " + " | ".join(meta)
        return f"{header}\n{self.text}"


def _chunk_from_dict(data: dict[str, Any], path: Path) -> Chunk:
    try:
        eligibility = data.get("eligibility")
        return Chunk(
            id=data["id"],
            title=data["title"],
            section=data["section"]["title"],
            country=data["country"],
            sub_company=tuple(data["sub_company"]),
            applies_to=tuple(data["applies_to"]),
            paid_status=data["paid_status"],
            eligibility=eligibility["who"] if eligibility else None,
            text=data["text"],
        )
    except (KeyError, TypeError) as exc:
        raise KnowledgeError(f"{path}: malformed chunk ({exc!r})") from exc


def load_chunks(directory: Path) -> list[Chunk]:
    """Load all chunks, ordered by filename (i.e. handbook order)."""
    files = sorted(directory.glob("*.json"))
    if not files:
        raise KnowledgeError(f"no *.json chunks found in {directory}")
    chunks: list[Chunk] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KnowledgeError(f"{path}: invalid JSON ({exc})") from exc
        chunks.append(_chunk_from_dict(data, path))
    logger.info("knowledge loaded chunks=%d dir=%s", len(chunks), directory)
    return chunks


def select_chunks(
    chunks: list[Chunk],
    *,
    country: str | None = None,
    sub_company: str | None = None,
) -> list[Chunk]:
    """Chunks matching the employee profile (None = no filter); raises KnowledgeError if none match."""
    selected = [
        c
        for c in chunks
        if (country is None or c.country == country)
        and (sub_company is None or sub_company in c.sub_company)
    ]
    if not selected:
        raise KnowledgeError(f"no chunks match country={country!r}, sub_company={sub_company!r}")
    return selected


def render_context(
    chunks: list[Chunk],
    *,
    country: str | None = None,
    sub_company: str | None = None,
) -> str:
    """Render (optionally filtered) chunks into one context block."""
    selected = select_chunks(chunks, country=country, sub_company=sub_company)
    return "\n\n".join(c.render() for c in selected)
