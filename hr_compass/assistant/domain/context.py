"""The sources the answer model sees: the retrieved chunks that fit the token budget, each under a label.

    [S1] Employee Handbook · Section 2 > 2-5. Remote Work · USA · effective 2026-01-01
    <chunk text>

The header names the document by its title, not its path (paths hold people's names).
"""

from __future__ import annotations

from dataclasses import dataclass

from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Hit
from hr_compass.shared.tokens import Tokenizer


@dataclass(frozen=True, slots=True)
class Context:
    text: str
    sources: dict[str, ChunkRecord]     # label ("S1") -> chunk
    tokens: int


def header(label: str, chunk: ChunkRecord) -> str:
    parts = [f"[{label}] {chunk.title or 'untitled'}", chunk.section or "no section", chunk.country or "company-wide"]
    if chunk.effective:
        parts.append(f"effective {chunk.effective}")
    return " · ".join(parts)


def build_context(hits: list[Hit], budget: int, tokenizer: Tokenizer) -> Context:
    """Hits in rank order; a chunk that does not fit the remaining budget is skipped, a smaller one may still fit."""
    parts: list[str] = []
    sources: dict[str, ChunkRecord] = {}
    used = 0
    for hit in hits:
        label = f"S{len(sources) + 1}"
        block = f"{header(label, hit.chunk)}\n{hit.chunk.text}"
        size = tokenizer.count(block)
        if used + size > budget:
            continue
        parts.append(block)
        sources[label] = hit.chunk
        used += size
    return Context("\n\n".join(parts), sources, used)
