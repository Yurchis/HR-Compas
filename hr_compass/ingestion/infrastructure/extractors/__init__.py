"""Text extraction by file type: a source document -> clean markdown-ish text (+ the title stored in the file).

    python -m hr_compass.ingestion.infrastructure.extractors policy.pdf     # print the extracted text
"""

from __future__ import annotations

import sys
from pathlib import Path

from hr_compass.ingestion.domain.document import Extracted
from hr_compass.ingestion.infrastructure.extractors.docx import extract_docx
from hr_compass.ingestion.infrastructure.extractors.html import extract_html
from hr_compass.ingestion.infrastructure.extractors.pdf import extract_pdf

SUPPORTED = frozenset({".html", ".htm", ".pdf", ".docx"})

__all__ = ["SUPPORTED", "Extracted", "extract"]


def extract(path: Path) -> Extracted:
    """Dispatch by file type; raises ValueError for an unsupported one."""
    suffix = Path(path).suffix.lower()
    if suffix in (".html", ".htm"):
        return Extracted(extract_html(path))
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".docx":
        return extract_docx(path)
    raise ValueError(f"unsupported file type: {suffix}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m hr_compass.ingestion.infrastructure.extractors <file.html|file.pdf|file.docx>")
    sys.stdout.reconfigure(encoding="utf-8")
    result = extract(Path(sys.argv[1]))
    print(result.text.replace("\f", "\n\n<<<page break>>>\n\n"))
    if result.needs_ocr:
        print("\nneeds_ocr: no usable text layer (a scan?) - send to OCR, not to the index", file=sys.stderr)
