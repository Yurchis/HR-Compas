from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt

from hr_compass.ingestion.infrastructure.extractors import extract
from hr_compass.ingestion.infrastructure.extractors.docx import extract_docx


def _save(doc, tmp_path: Path, name: str = "doc.docx") -> Path:
    path = tmp_path / name
    doc.save(str(path))
    return path


def test_heading_styles_become_markdown_headings(tmp_path: Path):
    doc = Document()
    doc.add_heading("VPN setup", level=0)  # Title
    doc.add_paragraph("All remote connections go through the VPN.")
    doc.add_heading("Install the client", level=1)
    doc.add_paragraph("Ask the IT desk.")
    doc.sections[0].header.paragraphs[0].text = "It Company - Internal"  # page header: not body text

    assert extract_docx(_save(doc, tmp_path)).text == (
        "# VPN setup\n\nAll remote connections go through the VPN.\n\n## Install the client\n\nAsk the IT desk."
    )


def test_numbered_and_bulleted_lists_keep_their_markers(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("Steps:")
    for step in ("Open the Software Center.", "Install the VPN client.", "Sign in."):
        doc.add_paragraph(step, style="List Number")
    doc.add_paragraph("You will need:")
    doc.add_paragraph("a company laptop", style="List Bullet")
    doc.add_paragraph("your phone", style="List Bullet")

    assert extract_docx(_save(doc, tmp_path)).text == (
        "Steps:\n\n"
        "1. Open the Software Center.\n2. Install the VPN client.\n3. Sign in.\n\n"
        "You will need:\n\n"
        "- a company laptop\n- your phone"
    )


def test_tables_become_markdown_rows_in_document_order(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("Servers:")
    table = doc.add_table(rows=3, cols=2)
    rows = [("Server", "Use for"), ("vpn-kyiv", "Ukraine | default"), ("vpn-warsaw", "EU")]
    for row, values in zip(table.rows, rows, strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    doc.add_paragraph("Pick the closest one.")

    assert extract_docx(_save(doc, tmp_path)).text == (
        "Servers:\n\n"
        "| Server | Use for |\n| --- | --- |\n| vpn-kyiv | Ukraine \\| default |\n| vpn-warsaw | EU |\n\n"
        "Pick the closest one."
    )


def test_merged_cells_are_written_once(tmp_path: Path):
    doc = Document()
    table = doc.add_table(rows=2, cols=3)
    merged = table.cell(0, 0).merge(table.cell(0, 1))
    merged.text = "Holidays"
    table.cell(0, 2).text = "Days"
    for cell, value in zip(table.rows[1].cells, ("US", "Floating", "11"), strict=True):
        cell.text = value

    expected = "| Holidays | Days |  |\n| --- | --- | --- |\n| US | Floating | 11 |"
    assert extract_docx(_save(doc, tmp_path)).text == expected


def test_bold_or_larger_short_lines_are_headings_without_heading_styles(tmp_path: Path):
    doc = Document()
    big = doc.add_paragraph().add_run("Section 1 - Governing Principles")
    big.font.size = Pt(16)
    doc.add_paragraph().add_run("Just Cause").bold = True
    doc.add_paragraph("Employment may end for a just cause. " * 5)
    doc.add_paragraph().add_run("This bold line is a sentence.").bold = True
    doc.add_paragraph("More body text that explains the policy in detail. " * 5)

    assert extract_docx(_save(doc, tmp_path)).text.split("\n\n")[:2] == ["# Section 1 - Governing Principles",
                                                                    "## Just Cause"]
    assert "\n\nThis bold line is a sentence.\n\n" in extract_docx(_save(doc, tmp_path)).text


def test_a_bold_date_at_the_top_of_a_letter_is_not_a_heading(tmp_path: Path):
    doc = Document()
    doc.add_paragraph().add_run("May 5, 2025").bold = True
    doc.add_paragraph().add_run("Employment Verification").bold = True
    doc.add_paragraph("This letter is to verify that the employee works with us since 2020. " * 4)

    assert extract_docx(_save(doc, tmp_path)).text.split("\n\n")[:2] == ["May 5, 2025", "# Employment Verification"]


def test_dispatch_reads_docx(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("Hello.")

    result = extract(_save(doc, tmp_path))
    assert (result.text, result.needs_ocr) == ("Hello.", False)
