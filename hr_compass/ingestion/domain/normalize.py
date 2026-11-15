"""Normalisation: one canonical text form, so that hashing, dedup and chunking see the same thing.

Input is the output of the extractors (`ingestion.infrastructure.extractors`: markdown-ish text, PDF pages
separated by `\\f`):

1. NFKC, CRLF -> LF, zero-width characters and the BOM removed;
2. pages split on `\\f`, running headers / footers (the same line at the edge of most pages) removed;
3. page numbers ("Page 2 of 3", "- 4 -") removed;
4. words hyphenated across lines joined: "secur-\\nity" -> "security";
5. trailing spaces stripped, runs of spaces collapsed, lines wrapped by the layout joined (`unwrap`),
   at most one blank line in a row.

Pages are joined with a newline, so a sentence broken by a page break is unwrapped like any other line.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata

logger = logging.getLogger(__name__)

ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")  # incl. BOM and soft hyphen
# "Page 2 of 3", "2 / 3", "стор. 2 з 3": a page number anywhere in the text.
PAGE_OF = re.compile(r"^\s*(page|p\.|стор(інка|\.)?|стр(аница|\.)?)?\s*\d+\s*(of|/|з|из|із)\s*\d+\s*$", re.IGNORECASE)
# Also "Page 2", "- 2 -", "2": only trusted at the top / bottom of a page.
EDGE_PAGE_NUMBER = re.compile(
    r"^(page|p\.|стор(інка|\.)?|стр(аница|\.)?)?\s*[-–—]?\s*\d+\s*[-–—]?\s*((of|/|з|из|із)\s*\d+)?$", re.IGNORECASE)
EDGE_LINES = 2              # running headers / footers live in the first / last lines of a page
REPEATED_SHARE = 0.6        # an edge line on at least this share of pages is a running header / footer
HEADING = re.compile(r"^(#{1,6} |\d+\.\s+[A-ZА-ЯІЇЄҐ])")
HEADING_LINE = re.compile(r"^#{1,6} ")
LIST_ITEM = re.compile(r"^\s*([-*] |\d+[.)]\s)")
HYPHENATED = re.compile(r"(\w)-[ \t]*\n[ \t]*([a-zа-яіїєґё])")  # the next line goes on in lowercase
UNWRAP_MIN_CHARS = 60       # a wrapped line is long; a short line is a title, a label or a paragraph's end


def _counts_pages(seen: dict[int, str]) -> bool:
    """Same line on every page, or the only numbers that differ move in step with the page index
    ("page 3" on page 3, "- 4 -" on page 5): a page counter, not content like "Section 1", "Section 7"."""
    numbers = {page: [int(n) for n in re.findall(r"\d+", line)] for page, line in seen.items()}
    columns = list(zip(*numbers.values(), strict=False))
    for col in columns:
        if len(set(col)) > 1 and len({value - page for value, page in zip(col, numbers, strict=True)}) > 1:
            return False
    return True


def page_furniture(pages: list[list[str]]) -> list[set[int]]:
    """Per page, the indexes of lines to drop: page numbers and running headers / footers.

    A running line is an edge line (first / last EDGE_LINES non-empty lines, not a `#` heading) found on
    most pages, either verbatim or with a number that counts pages ("Confidential - page 3"). It is kept
    once, where it first appears: it may carry metadata ("Effective 2026-01-15") that later steps look
    for; the repeats are noise."""
    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().casefold())

    edges = []
    for lines in pages:
        filled = [i for i, line in enumerate(lines) if line.strip() and not HEADING_LINE.match(line)]
        edges.append(sorted(set(filled[:EDGE_LINES] + filled[-EDGE_LINES:])))
    occurrences: dict[str, dict[int, str]] = {}  # key -> {page index: line}
    for page_no, (lines, idx) in enumerate(zip(pages, edges, strict=True)):
        for i in idx:
            occurrences.setdefault(key(lines[i]), {}).setdefault(page_no, lines[i].strip())
    needed = max(2, math.ceil(REPEATED_SHARE * len(pages)))
    repeated = {k for k, seen in occurrences.items() if len(seen) >= needed and _counts_pages(seen)}

    drop: list[set[int]] = []
    kept: set[str] = set()
    for lines, idx in zip(pages, edges, strict=True):
        page_drop = set()
        for i in idx:
            k = key(lines[i])
            if EDGE_PAGE_NUMBER.match(lines[i].strip()) or (k in repeated and k in kept):
                page_drop.add(i)
            elif k in repeated:
                kept.add(k)
        drop.append(page_drop)
    return drop


def unwrap(text: str) -> str:
    """Join lines that the layout broke inside a sentence; keep headings, list items and table rows."""
    out: list[str] = []
    for line in text.split("\n"):
        prev = out[-1] if out else ""
        joinable = (
            prev and line
            and len(prev) >= UNWRAP_MIN_CHARS
            and not prev.rstrip().endswith((".", ":", "!", "?", ";"))
            and not HEADING.match(prev) and not HEADING.match(line)
            and not LIST_ITEM.match(line)
            and not prev.lstrip().startswith("|") and not line.lstrip().startswith("|")
        )
        if joinable:
            out[-1] = f"{prev.rstrip()} {line.lstrip()}"
        else:
            out.append(line)
    return "\n".join(out)


def _collapse_spaces(line: str) -> str:
    """Runs of spaces / tabs -> one space; the leading indent (nested list items) is kept."""
    indent = re.match(r"^ *", line.replace("\t", "  ")).group()
    return indent + re.sub(r"[ \t]+", " ", line.strip())


def normalize(text: str) -> str:
    chars_in = len(text)
    # 1. one Unicode form, one line ending, no invisible characters
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text, invisible = ZERO_WIDTH.subn("", text)
    # 2-3. running headers / footers and page numbers, page by page
    pages = [page.split("\n") for page in text.split("\f")]
    furniture = 0
    if len(pages) > 1:
        drops = page_furniture(pages)
        furniture = sum(map(len, drops))
        pages = [[line for i, line in enumerate(lines) if i not in drop]
                 for lines, drop in zip(pages, drops, strict=True)]
    all_lines = [line for page in pages for line in page]
    lines = [line for line in all_lines if not PAGE_OF.match(line)]
    text = "\n".join(lines)
    # 4. words hyphenated across lines
    text, hyphenated = HYPHENATED.subn(r"\1\2", text)
    # 5. spaces, wrapped lines, blank lines
    text = "\n".join(_collapse_spaces(line) for line in text.split("\n"))
    before_unwrap = text.count("\n")
    text = unwrap(text)
    unwrapped = before_unwrap - text.count("\n")
    text = re.sub(r"(?<=[^\n])\n(?=#{1,6} )", "\n\n", text)  # a heading starts a block (also after a page join)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    logger.debug("normalize: pages=%d invisible chars=%d furniture lines=%d page-number lines=%d "
                 "hyphenations joined=%d wrapped lines joined=%d chars %d -> %d",
                 len(pages), invisible, furniture, len(all_lines) - len(lines), hyphenated, unwrapped,
                 chars_in, len(text))
    return text
