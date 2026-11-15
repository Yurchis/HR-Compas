"""DOCX: headings as `#` lines (by style or by formatting), numbered / bulleted lists as `1. ` / `- ` lines,
tables as `| a | b |` rows. Only the body is read (and its text boxes): page headers / footers live elsewhere."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from hr_compass.ingestion.domain.document import Extracted
from hr_compass.ingestion.infrastructure.extractors.text import HEADING_MAX_SHARE
from hr_compass.ingestion.infrastructure.extractors.text import clean as _clean
from hr_compass.ingestion.infrastructure.extractors.text import is_heading_text as _is_heading_text

logger = logging.getLogger(__name__)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
TOC_STYLE = re.compile(r"^(toc\s*\d|toc heading|table of figures)$", re.IGNORECASE)
TOC_TITLE = re.compile(r"^(table of contents|contents|зміст|содержание|оглавление)$", re.IGNORECASE)
UNORDERED_FORMATS = {"bullet", "none"}  # every other w:numFmt (decimal, lowerLetter, ...) is numbered


def _w(el, name: str):
    return el.find(f"{W_NS}{name}") if el is not None else None


def _wattr(el, name: str = "val") -> str | None:
    return el.get(f"{W_NS}{name}") if el is not None else None


def _style_chain(style):
    while style is not None:
        yield style
        style = style.base_style


def _style_heading_level(paragraph) -> int | None:
    """Title -> 0, Heading N -> N (also through custom styles based on them, and w:outlineLvl)."""
    outline = _wattr(_w(_w(paragraph._p, "pPr"), "outlineLvl"))
    for style in _style_chain(paragraph.style):
        name = (style.name or "").strip()
        if name.lower() == "title":
            return 0
        if m := HEADING_STYLE.match(name):
            return int(m.group(1))
        outline = outline or _wattr(_w(_w(style.element, "pPr"), "outlineLvl"))
    return int(outline) + 1 if outline and outline.isdigit() and int(outline) < 9 else None


def _numbering_formats(document) -> dict[tuple[str, int], str]:
    """(numId, level) -> w:numFmt ("decimal", "bullet", ...) from the numbering part."""
    try:
        numbering = document.part.numbering_part.element
    except (KeyError, NotImplementedError):
        return {}
    abstract: dict[str | None, dict[int, str]] = {}
    for an in numbering.findall(f"{W_NS}abstractNum"):
        abstract[_wattr(an, "abstractNumId")] = {
            int(_wattr(lvl, "ilvl") or 0): _wattr(_w(lvl, "numFmt")) or "decimal" for lvl in an.findall(f"{W_NS}lvl")}
    return {(_wattr(num, "numId"), level): fmt
            for num in numbering.findall(f"{W_NS}num")
            for level, fmt in abstract.get(_wattr(_w(num, "abstractNumId")), {}).items()}


def _list_item(paragraph) -> tuple[str, int] | None:
    """(numId, level) when the paragraph is a list item, directly or through its style."""
    num_pr = _w(_w(paragraph._p, "pPr"), "numPr")
    for style in _style_chain(paragraph.style):
        if num_pr is not None:
            break
        num_pr = _w(_w(style.element, "pPr"), "numPr")
    num_id = _wattr(_w(num_pr, "numId"))
    if num_id in (None, "0"):  # numId 0 switches numbering off
        return None
    level = _wattr(_w(num_pr, "ilvl"))
    return num_id, int(level) if level and level.isdigit() else 0


def _default_size(document) -> float:
    sz = document.styles.element.find(f"{W_NS}docDefaults/{W_NS}rPrDefault/{W_NS}rPr/{W_NS}sz")
    value = _wattr(sz)
    return int(value) / 2 if value and value.isdigit() else 10.0  # w:sz is in half-points; Word's default is 10


def _run_format(run, paragraph, default_size: float) -> tuple[float, bool]:
    """(font size in pt, bold) of a run, following the run -> paragraph style chain -> document default."""
    size = run.font.size.pt if run.font.size else None
    bold = run.bold
    for style in _style_chain(paragraph.style):
        if size is None and style.font.size:
            size = style.font.size.pt
        if bold is None and style.font.bold is not None:
            bold = style.font.bold
    return size or default_size, bool(bold)


def _paragraph_format(paragraph, default_size: float) -> tuple[float, bool]:
    """The size most of the text is set in, and whether all of it is bold."""
    sizes, all_bold, any_text = Counter(), True, False
    for run in paragraph.runs:
        text = run.text.strip()
        if not text:
            continue
        size, bold = _run_format(run, paragraph, default_size)
        sizes[size] += len(text)
        all_bold &= bold
        any_text = True
    return (sizes.most_common(1)[0][0] if sizes else default_size), all_bold and any_text


def _cell_text(cell) -> str:
    return " ".join(_clean(p.text).replace("\n", " ") for p in cell.paragraphs if p.text.strip()).replace("|", "\\|")


def _docx_table(table) -> list[str]:
    rows = []
    for row in table.rows:
        cells, previous = [], None
        for cell in row.cells:
            if previous is not None and cell._tc is previous._tc:
                continue  # a horizontally merged cell is reported once per grid column
            cells.append(_cell_text(cell))
            previous = cell
        if any(cells):
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    if width == 1:  # a one-column table is a layout box, not data: keep its text as paragraphs
        return [r[0] for r in rows if r[0]]
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    lines.insert(1, "|" + " --- |" * width)
    return ["\n".join(lines)]


def _is_toc(sdt) -> bool:
    gallery = sdt.find(f"{W_NS}sdtPr/{W_NS}docPartObj/{W_NS}docPartGallery")
    return (_wattr(gallery) or "").lower() == "table of contents"


def _text_boxes(p_el):
    """w:txbxContent of the shapes anchored in a paragraph; each shape once (not its VML fallback copy)."""
    for box in p_el.iter(f"{W_NS}txbxContent"):
        ancestor = box.getparent()
        while ancestor is not None and ancestor is not p_el:
            if ancestor.tag in (MC_FALLBACK, f"{W_NS}txbxContent"):
                break  # the fallback duplicate, or a box nested in another box (walked with its parent)
            ancestor = ancestor.getparent()
        else:
            yield box


def _docx_items(document):
    """Paragraphs and tables in reading order: body, content controls, text boxes; no table of contents."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def walk(parent):
        for el in parent.iterchildren():
            if el.tag == f"{W_NS}p":
                for box in _text_boxes(el):
                    yield from walk(box)
                paragraph = Paragraph(el, document)
                style = (paragraph.style.name if paragraph.style else "") or ""
                if not TOC_STYLE.match(style) and not TOC_TITLE.match(paragraph.text.strip()):
                    yield paragraph
            elif el.tag == f"{W_NS}tbl":
                yield Table(el, document)
            elif el.tag == f"{W_NS}sdt" and not _is_toc(el) and (content := _w(el, "sdtContent")) is not None:
                yield from walk(content)

    yield from walk(document.element.body)


def _heading_keys(paragraphs, default_size: float) -> dict[int, tuple]:
    """Rank key per heading paragraph (index -> key): larger font first, then bold, then the heading style.

    Heading-styled paragraphs (Title, Heading N) are always headings. A formatting-only heading is a short
    line, set larger than the body text of this document or all bold, that does not read as a sentence or
    a label. Ranking all of them by how they look puts real documents, which mix both, in one hierarchy."""
    formats = {i: _paragraph_format(p, default_size) for i, p in enumerate(paragraphs)}
    chars, bold_chars = Counter(), 0
    for i, p in enumerate(paragraphs):
        size, bold = formats[i]
        chars[size] += len(p.text)
        bold_chars += len(p.text) if bold else 0
    total = sum(chars.values()) or 1
    body = chars.most_common(1)[0][0] if chars else default_size
    bold_is_heading = bold_chars / total <= HEADING_MAX_SHARE  # a mostly-bold document has no bold headings

    keys: dict[int, tuple] = {}
    for i, p in enumerate(paragraphs):
        text = _clean(p.text)
        if not text:
            continue
        size, bold = formats[i]
        style_level = _style_heading_level(p)
        if style_level is not None:
            keys[i] = (-max(size, body), not bold, style_level)
        elif _list_item(p) or not _is_heading_text(text) or text.endswith((".", ":")):
            continue
        elif size > body and chars[size] / total <= HEADING_MAX_SHARE:
            keys[i] = (-size, not bold, 99)
        elif bold and bold_is_heading:
            keys[i] = (-body, False, 99)
    return keys


def extract_docx(path: Path) -> Extracted:
    """The text (see the module docstring) and the core-properties title, from one read of the file."""
    document = _load(path)
    return Extracted(_render(document), metadata_title=document.core_properties.title or "")


def _load(path: Path):
    from docx import Document

    return Document(str(path))


def _render(document) -> str:
    """Headings as `#` lines, numbered / bulleted lists as `1. ` / `- ` lines, tables as `| a | b |` rows.

    Only the body is read (and its text boxes): page headers / footers live in other parts of the file."""
    from docx.table import Table

    default_size = _default_size(document)
    formats = _numbering_formats(document)
    items = list(_docx_items(document))
    paragraphs = [i for i in items if not isinstance(i, Table)]
    keys = _heading_keys(paragraphs, default_size)
    rank = {key: n for n, key in enumerate(sorted(set(keys.values())), start=1)}
    level_of = {id(paragraphs[i]): min(6, rank[key]) for i, key in keys.items()}
    logger.debug("docx: paragraphs=%d tables=%d headings=%d (levels %d) numbered lists=%d default size=%spt",
                 len(paragraphs), len(items) - len(paragraphs), len(keys), len(rank),
                 len({k[0] for k in formats}), default_size)

    blocks: list[str] = []
    counters: dict[tuple[str, int], int] = {}
    in_list = False
    for item in items:
        if isinstance(item, Table):
            blocks += _docx_table(item)
            in_list = False
            continue
        text = _clean(item.text)
        if not text:
            continue
        level = level_of.get(id(item))
        list_item = None if level else _list_item(item)
        if level:
            blocks.append(f"{'#' * level} {text.replace(chr(10), ' ')}")
        elif list_item:
            num_id, depth = list_item
            fmt = formats.get(list_item, "decimal" if "number" in (item.style.name or "").lower() else "bullet")
            for key in [k for k in counters if k[0] == num_id and k[1] > depth]:
                del counters[key]  # a deeper list restarts after its parent item
            if fmt in UNORDERED_FORMATS:
                marker = "- "
            else:
                counters[list_item] = counters.get(list_item, 0) + 1
                marker = f"{counters[list_item]}. "
            line = "  " * depth + marker + text.replace("\n", " ")
            if in_list:
                blocks[-1] += "\n" + line  # consecutive list items stay one block
            else:
                blocks.append(line)
        else:
            blocks.append(text)
        in_list = bool(list_item)
    return "\n\n".join(blocks)
