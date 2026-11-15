from __future__ import annotations

import json
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from hr_compass.ingestion.domain.chunking import ChunkDraft
from hr_compass.ingestion.domain.document import (
    PIPELINE_VERSION,
    Document,
    chunk_records,
    clean_metadata_title,
    country_of,
    dataset_version,
    effective_date,
    title_of,
)
from hr_compass.ingestion.infrastructure.extractors.docx import extract_docx
from hr_compass.shared.tokens import TiktokenTokenizer

COUNTRIES = {"Usa": "USA", "UA": "UA", "costa Rica": "Costa Rica"}


@pytest.mark.parametrize("text, date", [
    ("Northwind — Internal\nEffective 2026-01-15\n# Policy", "2026-01-15"),
    ("Effective date: 2026-09-01. Replaces the version of 2026-01-15.", "2026-09-01"),
    ("This policy is effective as of January 1, 2026.", "2026-01-01"),
    ("# Vacation Policy Update: Accrual Policy Eff. 1/1/26", "2026-01-01"),
    ("Effective 01/15/2026", "2026-01-15"),
    ("Effective 13/45/2026 is not a date", None),
    ("No date here, effective immediately.", None),
])
def test_effective_date(text, date):
    assert effective_date(text) == date


def test_title_prefers_the_first_top_level_heading_over_a_stamp():
    assert title_of("Internal\nEffective 2026-01-15\n\n# Remote Work Policy\n\n## 1. Purpose") == "Remote Work Policy"


def test_title_falls_back_to_file_metadata_then_file_name_then_first_line():
    assert title_of("Some text.", "Commuter Benefits") == "Commuter Benefits"
    assert title_of("May 5, 2025\n\nDear candidate,", "Microsoft Word - draft.docx",
                    "Offer_Letter  Template.docx") == "Offer Letter Template"
    assert title_of("## Section\n\nSome text.") == "Section"


def test_metadata_placeholders_are_not_titles():
    assert clean_metadata_title("Microsoft Word - draft.docx") == ""
    assert clean_metadata_title("Untitled") == "" and clean_metadata_title(None) == ""
    assert clean_metadata_title(" Commuter Benefits ") == "Commuter Benefits"


def test_the_docx_title_is_read_in_the_same_pass_as_the_text(tmp_path: Path):
    doc = DocxDocument()
    doc.core_properties.title = "Commuter Benefits"
    doc.add_paragraph("Hello.")
    doc.save(str(tmp_path / "x.docx"))

    extracted = extract_docx(tmp_path / "x.docx")

    assert (extracted.text, extracted.metadata_title) == ("Hello.", "Commuter Benefits")


@pytest.mark.parametrize("source, country", [
    ("ai_course/Usa/Policies/Handbook/Handbook 2026.docx", "USA"),
    ("ai_course/UA/Processes/Onboarding/Onboarding EU.docx", "UA"),
    ("ai_course/costa Rica/Team Manual.pdf", "Costa Rica"),
    ("ai_course/Roles.pdf", None),                          # no country folder: company-wide
    ("ai_course/UA.pdf", None),                             # a file name is not a folder
])
def test_the_country_is_the_folder(source, country):
    assert country_of(source, COUNTRIES) == country


def test_chunk_records_carry_everything_retrieval_needs():
    doc = Document(source="UA/Finance/q3_budget.pdf", raw_hash="r" * 64, text="...", doc_hash="d" * 64,
                   title="Q3 Budget Summary", effective="2026-10-05", country="UA")
    drafts = [ChunkDraft("# Q3 Budget Summary\n\nTotal costs fell.", ("Q3 Budget Summary",)),
              ChunkDraft("Headcount is 312.", ("Q3 Budget Summary", "Headcount"))]

    records = chunk_records(doc, drafts, ("finance",), TiktokenTokenizer(), now="2026-11-12T10:00:00+00:00")

    assert records[1].to_dict() == {
        "chunk_id": "UA/Finance/q3_budget.pdf#1", "source": "UA/Finance/q3_budget.pdf", "title": "Q3 Budget Summary",
        "section": "Q3 Budget Summary > Headcount", "access": ["finance"], "doc_hash": "d" * 64, "chunk_index": 1,
        "n_tokens": 6, "text": "Headcount is 312.", "pipeline_version": PIPELINE_VERSION,
        "ingested_at": "2026-11-12T10:00:00+00:00", "effective": "2026-10-05", "country": "UA",
    }
    json.dumps([r.to_dict() for r in records])  # JSON-ready


# ---------------------------------------------------------------- dataset version

FILES = {
    "Policies/vacation.pdf": {"raw_hash": "a" * 64, "status": "ok", "title": "Paid Vacation"},
    "IT/vpn.docx": {"raw_hash": "b" * 64, "status": "ok"},
}


def test_same_inputs_give_the_same_dataset_version_whatever_the_order_or_the_other_fields():
    reordered = {k: {**FILES[k], "status": "near_duplicate", "title": "x"} for k in reversed(list(FILES))}

    assert dataset_version(FILES) == dataset_version(reordered)
    assert len(dataset_version(FILES)) == 64


def test_any_change_in_inputs_pipeline_or_config_gives_a_new_dataset_version():
    config = {"access": {"": ["all_employees"]}}
    base = dataset_version(FILES, config=config)
    others = [
        dataset_version({**FILES, "IT/vpn.docx": {"raw_hash": "c" * 64}}, config=config),
        dataset_version({**FILES, "HR/new.pdf": {"raw_hash": "d" * 64}}, config=config),
        dataset_version({"IT/vpn.docx": FILES["IT/vpn.docx"]}, config=config),
        dataset_version({"Policies/vacation_v2.pdf": FILES["Policies/vacation.pdf"],
                         "IT/vpn.docx": FILES["IT/vpn.docx"]}, config=config),
        dataset_version(FILES, pipeline_version="ingest-v9", config=config),
        dataset_version(FILES, config={"access": {"": ["hr"]}}),
    ]

    assert base not in others and len(set(others)) == len(others)
