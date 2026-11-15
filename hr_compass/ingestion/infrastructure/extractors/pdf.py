"""PDF: text page by page, pages separated by `\\f`; running headers / footers and page numbers are dropped,
headings (lines set larger than the body text of *this* document) become `#` lines. A scan without a text
layer is flagged `needs_ocr` instead of silently producing an empty document. Joining lines wrapped by the
layout and words hyphenated across lines is left to normalisation."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from hr_compass.ingestion.domain.document import Extracted
from hr_compass.ingestion.domain.normalize import ZERO_WIDTH, page_furniture
from hr_compass.ingestion.infrastructure.extractors.text import BULLETS, HEADING_MAX_SHARE, MAX_HEADING_LEVEL
from hr_compass.ingestion.infrastructure.extractors.text import is_heading_text as _is_heading_text

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 50     # less text than this per page on average: no usable text layer (a scan)
WORD_PER_LINE_MIN = 20      # a page with at least this many lines ...
WORD_PER_LINE_SHARE = 0.6   # ... most of them single words was placed word by word: use layout mode


@dataclass(slots=True)
class _Line:
    text: str
    size: float  # effective font size in points (0.0: unknown)


def _scale(tm: list[float], cm: list[float]) -> float:
    """Vertical scale of the text matrix times the current transformation matrix."""
    c = tm[2] * cm[0] + tm[3] * cm[2]
    d = tm[2] * cm[1] + tm[3] * cm[3]
    return math.hypot(c, d) or 1.0


def _page_no(page) -> str:
    """1-based page number for log lines (pypdf counts from 0, -1 when unknown)."""
    number = getattr(page, "page_number", None)
    return str(number + 1) if isinstance(number, int) and number >= 0 else "?"


def _page_lines(page) -> list[_Line]:
    """The page's lines with the font size each was set in (pypdf reports it per text run)."""
    runs: list[tuple[str, float]] = []

    def visit(text, cm, tm, font, size):
        runs.append((text, round((size or 0) * _scale(tm, cm), 1)))

    text = page.extract_text(visitor_text=visit) or ""
    words_per_line = [len(line.split()) for line in text.split("\n") if line.strip()]
    if len(words_per_line) >= WORD_PER_LINE_MIN and words_per_line.count(1) / len(words_per_line) > WORD_PER_LINE_SHARE:
        # Justified text placed word by word: pypdf returns one word per line. Rebuild the lines from the
        # glyph positions instead (font sizes are lost for this page, so it gets no headings).
        logger.debug("pdf page %s: text placed word by word, re-extracted in layout mode", _page_no(page))
        text = page.extract_text(extraction_mode="layout") or ""
        return [_Line(re.sub(r"\s+", " ", ZERO_WIDTH.sub("", line)).strip(), 0.0) for line in text.split("\n")]
    if "".join(t for t, _ in runs) != text:  # runs do not add up to the text: keep the text, skip sizes
        logger.debug("pdf page %s: font runs do not match the text, no heading detection on this page",
                     _page_no(page))
        return [_Line(line, 0.0) for line in text.split("\n")]
    # A line's size is the size most of its characters are set in: pypdf sometimes glues a heading
    # and the following body text into one line, and that line is body text.
    lines: list[_Line] = []
    current, sizes = "", Counter()
    for run, run_size in runs:
        for i, part in enumerate(run.split("\n")):
            if i:
                lines.append(_Line(current, sizes.most_common(1)[0][0] if sizes else 0.0))
                current, sizes = "", Counter()
            current += part
            if part.strip():
                sizes[run_size] += len(part.strip())
    lines.append(_Line(current, sizes.most_common(1)[0][0] if sizes else 0.0))
    for line in lines:
        line.text = re.sub(r"\s+", " ", ZERO_WIDTH.sub("", line.text)).strip()
    return lines


def _drop_page_furniture(pages: list[list[_Line]]) -> int:
    """Remove page numbers and running headers / footers before headings are detected (see page_furniture).
    Returns how many lines were removed."""
    removed = 0
    for lines, drop in zip(pages, page_furniture([[line.text for line in lines] for lines in pages]), strict=True):
        for i in drop:
            lines[i].text = ""
        removed += len(drop)
    return removed


def _heading_levels(pages: list[list[_Line]]) -> dict[float, int]:
    """Font sizes larger than the body size of this document -> heading level (largest = 1)."""
    chars = Counter()
    for lines in pages:
        for line in lines:
            if line.text and line.size:
                chars[line.size] += len(line.text)
    if not chars:
        return {}
    body = chars.most_common(1)[0][0]
    total = sum(chars.values())
    margin = max(0.2, body * 0.02)  # sub-point differences are rounding noise, not a heading
    sizes = sorted((s for s in chars if s - body >= margin and chars[s] / total <= HEADING_MAX_SHARE), reverse=True)
    levels: dict[float, int] = {}
    for size in sizes:  # sizes within 0.2pt of each other are the same level
        prev = next((s for s in levels if abs(s - size) < 0.2), None)
        level = levels[prev] if prev is not None else len(set(levels.values())) + 1
        if level > MAX_HEADING_LEVEL:
            break  # a 4th, 5th ... larger size is emphasis (slides), not document structure
        levels[size] = level
    return levels


def _render_page(lines: list[_Line], levels: dict[float, int]) -> str:
    out: list[str] = []
    last_level = 0
    for line in lines:
        level = levels.get(line.size, 0) if line.text and _is_heading_text(line.text) else 0
        if level and level == last_level:  # a heading wrapped over two lines
            out[-1] += " " + line.text
            continue
        if not line.text:
            out.append("")
        elif level:
            out += ["", f"{'#' * level} {line.text}"]  # a heading is a block of its own
        else:
            if last_level:
                out.append("")
            out.append(BULLETS.sub("- ", line.text))
        last_level = level
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def extract_pdf(path: Path) -> Extracted:
    """Text per page, pages separated by `\\f`, the scan flag and the /Title, from one read of the file."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        logger.debug("pdf is encrypted: trying the empty user password")
        reader.decrypt("")  # an owner-password-only PDF opens with the empty user password
    pages = [_page_lines(page) for page in reader.pages]
    n_chars = sum(len(line.text.replace(" ", "")) for lines in pages for line in lines)
    needs_ocr = bool(pages) and n_chars < MIN_CHARS_PER_PAGE * len(pages)
    logger.debug("pdf: pages=%d non-space chars=%d (OCR threshold %d) needs_ocr=%s",
                 len(pages), n_chars, MIN_CHARS_PER_PAGE * len(pages), needs_ocr)
    removed = _drop_page_furniture(pages)
    levels = _heading_levels(pages)
    logger.debug("pdf: removed %d page-number / running header-footer line(s); heading sizes %s",
                 removed, {size: f"h{level}" for size, level in sorted(levels.items(), reverse=True)} or "none")
    return Extracted("\f".join(_render_page(lines, levels) for lines in pages), needs_ocr, _title(reader))


def _title(reader: PdfReader) -> str:
    try:
        return (reader.metadata.title or "") if reader.metadata else ""
    except Exception as exc:  # broken metadata must not fail the document
        logger.debug("pdf metadata unreadable: %s: %s", type(exc).__name__, exc)
        return ""
