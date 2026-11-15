"""A source document after extraction: its metadata, and the chunk records made from it.

Everything here is pure: the file was read by an extractor, the access groups come from the AccessPolicy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from hr_compass.ingestion.domain.chunking import ChunkDraft
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.shared.tokens import Tokenizer

PIPELINE_VERSION = "ingest-v2"   # bump when extraction / normalisation / chunking / record fields change the output

# "Effective 2026-01-15", "Effective date: 2026-01-15"
EFFECTIVE_ISO = re.compile(r"\beffective(?:\s+date)?(?:\s+as\s+of)?\s*:?\s*(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
# "Effective January 1, 2026"
EFFECTIVE_LONG = re.compile(r"\beffective(?:\s+date)?(?:\s+as\s+of)?\s*:?\s*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})",
                            re.IGNORECASE)
# "Eff. 1/1/26", "Effective 01/15/2026" (US month/day/year)
EFFECTIVE_US = re.compile(r"\beff(?:ective|\.)(?:\s+date)?\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", re.IGNORECASE)
JUNK_TITLE = re.compile(r"^(microsoft (word|powerpoint) - |untitled|document\d*$)|\.(docx?|pdf|pptx?)$", re.IGNORECASE)
TITLE_CHARS = 120


@dataclass(frozen=True, slots=True)
class Extracted:
    """What an extractor returns for one file."""

    text: str                   # markdown-ish text; PDF pages separated by \f
    needs_ocr: bool = False     # a scan without a usable text layer: not indexed
    metadata_title: str = ""    # the title stored in the file (PDF /Title, DOCX core properties)


@dataclass(frozen=True, slots=True)
class Document:
    source: str                 # path relative to the input folder
    raw_hash: str               # sha256 of the file bytes: did the file change?
    text: str                   # normalised text
    doc_hash: str               # content hash of the text: is the content the same?
    title: str = ""
    effective: str | None = None
    country: str | None = None


def effective_date(text: str) -> str | None:
    """The first "Effective ..." date in the text, as YYYY-MM-DD."""
    candidates = []
    if m := EFFECTIVE_ISO.search(text):
        candidates.append((m.start(), m.group(1)))
    if m := EFFECTIVE_LONG.search(text):
        with suppress(ValueError):   # "Effective March 32, 2026" is not a date
            day = datetime.strptime(re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", m.group(1))), "%B %d, %Y")
            candidates.append((m.start(), day.date().isoformat()))
    if m := EFFECTIVE_US.search(text):
        month, day_of_month, year = (int(g) for g in m.groups())
        year += 2000 if year < 100 else 0
        with suppress(ValueError):
            candidates.append((m.start(), datetime(year, month, day_of_month).date().isoformat()))
    return min(candidates)[1] if candidates else None


def clean_metadata_title(title: str | None) -> str:
    """The title stored in the file (PDF /Title, DOCX core properties), unless it is a placeholder."""
    title = (title or "").strip()
    return "" if JUNK_TITLE.search(title) else title


def title_of(text: str, metadata_title: str = "", file_name: str = "") -> str:
    """The first top-level `# ` heading; else the file's own title; else the file name; else the first line.

    The first line is the last resort: in a PDF it may be a stamp ("Internal"), in a letter a date or
    "ADDRESS" - a file name like "Offer Letter Template" says more."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:TITLE_CHARS]
    if meta := clean_metadata_title(metadata_title):
        return meta[:TITLE_CHARS]
    if stem := re.sub(r"[_\s]+", " ", file_name.split(".")[0]).strip():
        return stem[:TITLE_CHARS]
    for line in text.splitlines():
        if line.strip():
            return line.lstrip("#").strip()[:TITLE_CHARS]
    return ""


def country_of(source: str, countries: Mapping[str, str]) -> str | None:
    """The country of the first folder of `source` named in [ingest].countries; None = company-wide."""
    for folder in PurePosixPath(source).parts[:-1]:
        if folder in countries:
            return countries[folder]
    return None


def chunk_records(doc: Document, drafts: list[ChunkDraft], access: tuple[str, ...], tokenizer: Tokenizer,
                  now: str) -> list[ChunkRecord]:
    """One record per chunk draft."""
    return [
        ChunkRecord(chunk_id=f"{doc.source}#{i}", source=doc.source, title=doc.title, section=draft.section,
                    access=access, doc_hash=doc.doc_hash, chunk_index=i, n_tokens=tokenizer.count(draft.text),
                    text=draft.text, pipeline_version=PIPELINE_VERSION, ingested_at=now, effective=doc.effective,
                    country=doc.country)
        for i, draft in enumerate(drafts)
    ]


def dataset_version(files: Mapping[str, Mapping[str, Any]], pipeline_version: str = PIPELINE_VERSION,
                    config: Mapping[str, Any] | None = None) -> str:
    """sha256 over the pipeline version, each file's raw_hash (keyed by its path) and the config: the same
    inputs give the same id, any changed, added or removed file a new one. Statuses, titles or timestamps do
    not count: only what changes the output."""
    payload = {
        "pipeline_version": pipeline_version,
        "files": {source: info["raw_hash"] for source, info in files.items()},
        "config": config or {},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
