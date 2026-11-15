"""Chunking of normalised text (`ingestion.domain.normalize`).

- `chunk_by_headings`: split on headings, then pack whole blocks (paragraphs, lists, tables) up to max_tokens.
  A block is never cut in the middle; a block too big for one chunk is split only between its rows / items /
  sentences. Each chunk knows its section path (("Paid Vacation", "New Hires"));
- `chunk_fixed`: the baseline sliding window of tokens: simple, but cuts sentences, tables and sections.

Token counts come from the `Tokenizer` port, so this module has no model dependency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from hr_compass.shared.tokens import Tokenizer

logger = logging.getLogger(__name__)

FIXED_OVERLAP = 20          # overlap for the fixed-size baseline

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
# "2. Eligibility", "3.1 Approval": a short numbered title (a PDF without font sizes has no "#").
NUMBERED_TITLE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-ZА-ЯІЇЄҐ]")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'«“(\[]?[A-ZА-ЯІЇЄҐ0-9])")
LIST_ITEM = re.compile(r"^([-*] |\d+[.)]\s)")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk before it becomes a record: its text and the heading path it belongs to."""

    text: str
    path: tuple[str, ...] = ()

    @property
    def section(self) -> str:
        return " > ".join(self.path)


def is_heading(block: str) -> bool:
    """A markdown heading, or a one-line short numbered title like "2. Eligibility".
    "1. Open the Software Center." is a list item, not a heading: it is a sentence."""
    line = block.strip()
    if "\n" in line:
        return False  # a heading is a block of its own; "1. a\n2. b" is a list
    if line.startswith("#"):
        return bool(MD_HEADING.match(line))
    return bool(NUMBERED_TITLE.match(line)) and len(line) < 60 and not line.endswith((".", ":", ";"))


def _heading(block: str) -> tuple[int, str]:
    """(level, title). Numbered titles sit below every markdown level: "2." -> 7, "2.1" -> 8."""
    line = block.strip()
    if m := MD_HEADING.match(line):
        return len(m.group(1)), m.group(2).strip()
    number = NUMBERED_TITLE.match(line).group(1)
    return 6 + number.count(".") + 1, line


# ---------------------------------------------------------------- baseline


def chunk_fixed(text: str, tokenizer: Tokenizer, size: int, overlap: int = FIXED_OVERLAP) -> list[ChunkDraft]:
    """Baseline: a sliding window of tokens. Simple, but cuts sentences, tables and sections."""
    tokens = tokenizer.encode(text)
    chunks, start = [], 0
    while start < len(tokens):
        chunks.append(ChunkDraft(tokenizer.decode(tokens[start:start + size])))
        if start + size >= len(tokens):
            break
        start += size - overlap
    logger.debug("chunk_fixed: tokens=%d size=%d overlap=%d chunks=%d", len(tokens), size, overlap, len(chunks))
    return chunks


# ---------------------------------------------------------------- by headings


class _Packer:
    """Splits blocks too big for one chunk at safe places, counting tokens with the given tokenizer."""

    def __init__(self, tokenizer: Tokenizer) -> None:
        self.count = tokenizer.count

    def split_block(self, block: str, max_tokens: int) -> list[str]:
        """Split only at table rows (the header repeated in every piece), list items or sentences.
        A single row / item / sentence is never cut, even if it is too big."""
        lines = block.split("\n")
        if all(line.lstrip().startswith("|") for line in lines):
            header = lines[:2] if len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= {"-", " ", ":"} else []
            return self.pack(lines[len(header):], max_tokens, sep="\n", prefix="\n".join(header))
        if LIST_ITEM.match(lines[0]):
            items: list[str] = []
            for line in lines:  # a nested item ("  - x") belongs to the item above it
                if items and not LIST_ITEM.match(line):
                    items[-1] += "\n" + line
                else:
                    items.append(line)
            return self.pack(items, max_tokens, sep="\n")
        return self.pack(SENTENCE_END.split(block), max_tokens, sep=" ")

    def pack(self, units: list[str], max_tokens: int, sep: str, prefix: str = "") -> list[str]:
        """Greedily join units (with sep) while the result fits max_tokens; prefix starts every piece."""
        pieces: list[str] = []
        current: list[str] = []
        for unit in units:
            candidate = sep.join([*current, unit])
            if current and self.count(f"{prefix}\n{candidate}" if prefix else candidate) > max_tokens:
                pieces.append(sep.join(current))
                current = [unit]
            else:
                current.append(unit)
        if current:
            pieces.append(sep.join(current))
        return [f"{prefix}\n{p}" if prefix else p for p in pieces]


def chunk_by_headings(text: str, tokenizer: Tokenizer, max_tokens: int) -> list[ChunkDraft]:
    """Split on headings, then pack whole blocks up to max_tokens.

    A section's first chunk starts with its heading line(s); a heading with no text of its own (a title right
    above a subsection) is carried into the next chunk instead of becoming a chunk of its own."""
    packer = _Packer(tokenizer)
    count = tokenizer.count
    chunks: list[ChunkDraft] = []
    path: list[tuple[int, str]] = []  # the heading stack: (level, title)
    pending_headings: list[str] = []  # heading lines waiting for the section's first text
    current: list[str] = []           # blocks of the chunk being packed
    current_path: tuple[str, ...] = ()
    n_blocks = n_headings = n_split = 0

    def flush() -> None:
        if current:
            chunks.append(ChunkDraft("\n\n".join(current), current_path))
            current.clear()

    for block in (b.strip() for b in re.split(r"\n\s*\n", text)):
        if not block:
            continue
        n_blocks += 1
        if is_heading(block):
            n_headings += 1
            flush()
            level, title = _heading(block)
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, title))
            pending_headings.append(block)
            continue
        if not current:
            current_path = tuple(title for _, title in path)
        # Heading lines go in front of the section's first piece: leave room for them.
        heads = count("\n\n".join(pending_headings)) if pending_headings else 0
        budget = max(max_tokens // 2, max_tokens - heads)
        pieces = [block] if count(block) <= budget else packer.split_block(block, budget)
        if len(pieces) > 1:
            n_split += 1
        for piece in pieces:
            if current and count("\n\n".join([*current, piece])) > max_tokens:
                flush()  # pending headings are only ever waiting when current is empty
            current.extend(pending_headings)
            pending_headings.clear()
            current.append(piece)
    if pending_headings:  # headings at the very end with no text: keep them, they are content too
        if not current:
            current_path = tuple(title for _, title in path)
        current.extend(pending_headings)
    flush()
    logger.debug("chunk_by_headings: blocks=%d headings=%d oversized blocks split=%d chunks=%d max_tokens=%d",
                 n_blocks, n_headings, n_split, len(chunks), max_tokens)
    return chunks


def chunk_stats(chunks: list[ChunkDraft], tokenizer: Tokenizer, limit: int | None = None) -> dict:
    """What a chunking costs: chunks that start mid-sentence (or mid-word), cut table rows, the size distribution,
    chunks over `limit` tokens, tiny chunks (< 20 tokens) and chunks without a section path."""
    mid = sum(1 for c in chunks if c.text.lstrip()[:1].islower())  # a token often starts with a space
    cut_tables = sum(1 for c in chunks if any("|" in line and not (line.startswith("|") and line.endswith("|"))
                                              for line in c.text.strip().split("\n")))
    sizes = sorted(tokenizer.count(c.text) for c in chunks) or [0]
    stats = {"chunks": len(chunks), "starts_mid_sentence": mid, "cut_tables": cut_tables,
             "avg_tokens": round(sum(sizes) / len(sizes)), "median_tokens": sizes[len(sizes) // 2],
             "p95_tokens": sizes[min(len(sizes) - 1, int(len(sizes) * 0.95))], "max_tokens": sizes[-1],
             "under_20": sum(s < 20 for s in sizes), "no_section": sum(not c.path for c in chunks)}
    if limit is not None:
        stats["over_limit"] = sum(s > limit for s in sizes)
    return stats
