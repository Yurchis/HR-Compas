"""Text rules shared by the extractors: whitespace cleaning and what a heading line looks like."""

from __future__ import annotations

import re

from hr_compass.ingestion.domain.normalize import ZERO_WIDTH

HEADING_MAX_CHARS = 120     # longer "large" lines are body text set in a bigger font, not headings
HEADING_MAX_SHARE = 0.3     # a font size carrying more of the text than this is a body size
MAX_HEADING_LEVEL = 6       # the largest sizes above the body size become #, ##, ... ######
BULLETS = re.compile(r"^[•●▪■◦‣∙○□➢►]\s*")
_MONTHS = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
           r"|(?:січ|лют|берез|квіт|трав|черв|лип|серп|верес|жовт|листопад|груд)\w*"
           r"|(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*")
DATE_LINE = re.compile(  # "May 5, 2025", "5 May 2025", "5 травня 2025 р.", "2025-05-05", "05.05.2025"
    rf"^(?:(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}(?:\s*р\.|\s*г\.)?"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})$", re.IGNORECASE)


def clean(text: str) -> str:
    """Collapse whitespace inside lines (keeps the newlines that came from <br>)."""
    text = ZERO_WIDTH.sub("", text)
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def is_heading_text(text: str) -> bool:
    return (len(text) <= HEADING_MAX_CHARS and re.search(r"[^\W\d_]", text) is not None
            and not text[0].islower()  # a line starting in lowercase continues a sentence
            and not DATE_LINE.match(text)  # "May 5, 2025" at the top of a letter is set in bold, not a title
            and not text.endswith((",", ";")) and not BULLETS.match(text))
