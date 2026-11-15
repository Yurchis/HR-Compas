"""HTML: keep the article, drop navigation, cookie banners, scripts, forms and the page footer; headings become
markdown headings, lists `- ` / `1. ` lines and tables `| a | b |` rows, so a chunker can split on structure."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction

from hr_compass.ingestion.infrastructure.extractors.text import clean as _clean

logger = logging.getLogger(__name__)

# Never content: code, styling, embedded media and interactive widgets.
DROP_TAGS = ("script", "style", "noscript", "template", "iframe", "svg", "canvas", "object", "embed",
             "nav", "aside", "footer", "form", "button", "input", "select", "textarea", "dialog")
# ARIA landmarks of page chrome (not of the article).
DROP_ROLES = {"navigation", "banner", "contentinfo", "complementary", "menu", "menubar", "search", "dialog",
              "alertdialog"}
# Words in id / class / aria-label that mark page chrome ("cookie-banner", "main_nav", "breadcrumbs").
NOISE_WORDS = {"cookie", "cookies", "consent", "gdpr", "nav", "navbar", "navigation", "menu", "breadcrumb",
               "breadcrumbs", "sidebar", "skip", "popup", "modal", "newsletter", "share", "social"}
# Where the article lives, in order of preference; <body> is the fallback.
CONTENT_SELECTORS = ("main", "article", "[role=main]", "#content", "#main-content")

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "pre", "blockquote", "hr",
              "div", "section", "article", "main", "header", "figure", "figcaption", "dl", "dt", "dd",
              "details", "summary", "address", "li", "tr", "td", "th"}
SKIP_STRINGS = (Comment, Declaration, Doctype, ProcessingInstruction)


def extract_html(path: Path) -> str:
    """Extract the article of an HTML file. Bytes go to BeautifulSoup so `<meta charset>` is honoured."""
    return html_to_markdown(Path(path).read_bytes())


def html_to_markdown(markup: str | bytes) -> str:
    soup = BeautifulSoup(markup, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    dropped = _drop_noise(soup)
    selector, root = next(((sel, found) for sel in CONTENT_SELECTORS if (found := soup.select_one(sel))),
                          ("body" if soup.body else "document", soup.body or soup))
    blocks = [b for b in _blocks(root) if b.strip()]
    text = "\n\n".join(blocks)
    title_added = bool(page_title) and not re.search(r"^# ", text, re.MULTILINE)
    if title_added:
        text = f"# {_clean(page_title)}\n\n{text}" if text else f"# {_clean(page_title)}"
    logger.debug("html: dropped %d noise element(s), content root=%s, blocks=%d, <title> used as heading=%s",
                 dropped, selector, len(blocks), title_added)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- noise


def _is_noise(tag: Tag) -> bool:
    if tag.name in DROP_TAGS:
        return True
    if tag.name == "header" and not tag.find_parent(("article", "main")):
        return True  # the site header; an article's own <header> holds its title
    attrs = tag.attrs or {}
    if attrs.get("role") in DROP_ROLES or "hidden" in attrs or attrs.get("aria-hidden") == "true":
        return True
    if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style", ""), re.IGNORECASE):
        return True
    names = " ".join([*attrs.get("class", []), attrs.get("id", ""), attrs.get("aria-label", "")])
    if not NOISE_WORDS & set(re.split(r"[\s_-]+", names.lower())):
        return False
    # A layout wrapper like <div class="page has-sidebar"> may hold the article itself: keep it.
    return tag.name not in ("main", "article") and tag.find(("main", "article", "h1")) is None


def _drop_noise(soup: BeautifulSoup) -> int:
    """Remove page chrome; returns how many elements were dropped (not counting their descendants)."""
    dropped = 0
    for tag in soup.find_all(True):
        if not tag.decomposed and tag.name not in ("html", "body") and _is_noise(tag):
            tag.decompose()
            dropped += 1
    return dropped


# ---------------------------------------------------------------- rendering


def _inline(node: Tag) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, SKIP_STRINGS):
            continue
        if isinstance(child, NavigableString):
            parts.append(re.sub(r"\s+", " ", str(child)))
        elif child.name == "br":
            parts.append("\n")
        elif child.name in BLOCK_TAGS:
            parts.append(f" {_inline(child)} ")  # e.g. <p> inside <li>: keep the words apart
        else:
            parts.append(_inline(child))
    return "".join(parts)


def _list(tag: Tag, depth: int = 0) -> list[str]:
    lines: list[str] = []
    ordered = tag.name == "ol"
    start = tag.get("start", "1")
    number = int(start) if str(start).isdigit() else 1
    for li in tag.find_all("li", recursive=False):
        nested = [sub.extract() for sub in li.find_all(("ul", "ol"), recursive=False)]
        marker = f"{number}. " if ordered else "- "
        number += 1
        text = _clean(_inline(li)).replace("\n", " ")
        if text:
            lines.append("  " * depth + marker + text)
        for sub in nested:
            lines.extend(_list(sub, depth + 1))
    return lines


def _table(tag: Tag) -> str:
    rows = []
    for tr in tag.find_all("tr"):
        if tr.find_parent("table") is not tag:
            continue  # a row of a nested table
        cells = [_clean(_inline(c)).replace("\n", " ").replace("|", "\\|") for c in tr.find_all(("th", "td"))]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    lines.insert(1, "|" + " --- |" * width)
    return "\n".join(lines)


def _block(tag: Tag) -> list[str]:
    name = tag.name
    if re.fullmatch(r"h[1-6]", name):
        text = _clean(_inline(tag)).replace("\n", " ")
        return [f"{'#' * int(name[1])} {text}"] if text else []
    if name in ("ul", "ol"):
        return ["\n".join(_list(tag))]
    if name == "table":
        return [_table(tag)]
    if name == "pre":
        return [f"```\n{tag.get_text().strip(chr(10))}\n```"]
    if name == "blockquote":
        return ["\n".join(f"> {line}" for b in _blocks(tag) for line in b.split("\n"))]
    if name == "hr":
        return []
    return _blocks(tag)  # div, section, p, figure ...: walk the children


def _blocks(node: Tag) -> list[str]:
    """Render children in document order; loose inline text between blocks becomes a paragraph."""
    out: list[str] = []
    inline: list[str] = []

    def flush() -> None:
        text = _clean("".join(inline))
        inline.clear()
        if text:
            out.append(text)

    for child in node.children:
        if isinstance(child, SKIP_STRINGS):
            continue
        if isinstance(child, NavigableString):
            inline.append(re.sub(r"\s+", " ", str(child)))
        elif child.name == "br":
            inline.append("\n")
        elif child.name in BLOCK_TAGS:
            flush()
            out.extend(_block(child))
        else:
            inline.append(_inline(child))
    flush()
    return out
