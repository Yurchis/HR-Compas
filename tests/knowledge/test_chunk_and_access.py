from __future__ import annotations

import json
from pathlib import Path

import pytest

from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.knowledge.domain.retrieval import Query
from hr_compass.knowledge.infrastructure.files import load_access_rules
from hr_compass.shared.paths import ROOT
from tests.fakes import chunk

RULES = {"": ("all_employees",), "Finance/": ("finance",), "Finance/Payroll/": ("finance", "hr"),
         "*Offer Letter*": ("hr",)}
INHERITS = {"hr": ("all_employees",), "managers": ("all_employees",), "leadership": ("managers",)}


# ---------------------------------------------------------------- ChunkRecord


def test_a_record_survives_the_jsonl_round_trip():
    record = chunk("UA/vacation.pdf#3", section="Paid Vacation", country="UA", effective="2026-01-01")

    assert ChunkRecord.from_dict(json.loads(json.dumps(record.to_dict()))) == record


def test_old_records_without_country_load_as_company_wide():
    data = {k: v for k, v in chunk().to_dict().items() if k not in ("country", "effective")}

    assert ChunkRecord.from_dict(data).country is None


def test_a_record_missing_a_field_is_an_error():
    with pytest.raises(ValueError, match="misses"):
        ChunkRecord.from_dict({"chunk_id": "x#0"})


def test_the_section_path_heads_the_embedded_text_and_the_ref_hides_the_path():
    record = chunk("Recruitment/Offer Letter EU Jane.docx#2", "Salary 700.", section="Offer > Benefits")

    assert record.embedding_text() == "Offer > Benefits\nSalary 700."
    assert record.ref == f"{record.doc_hash[:12]}#2" and "Jane" not in record.ref
    assert chunk(section="").embedding_text() == chunk().text


# ---------------------------------------------------------------- access rules


@pytest.mark.parametrize("source, groups", [
    ("Policies/Paid Vacation.pdf", ("all_employees",)),
    ("Finance/q3_budget.pdf", ("finance",)),
    ("Finance/Payroll/rates.docx", ("finance", "hr")),        # the longest prefix wins
    ("Recruitment/Offer Letter EU.docx", ("hr",)),            # a glob over the whole path
])
def test_the_longest_matching_rule_wins(source, groups):
    assert AccessPolicy(RULES).groups_for(source) == groups


def test_an_unlisted_document_is_readable_by_nobody():
    assert AccessPolicy({"Finance/": ("finance",)}).groups_for("Policies/x.pdf") == ()


def test_groups_expand_along_the_hierarchy_transitively():
    policy = AccessPolicy(RULES, INHERITS)

    assert policy.expand(["hr"]) == {"hr", "all_employees"}
    assert policy.expand(["leadership"]) == {"leadership", "managers", "all_employees"}
    assert policy.expand([]) == frozenset() and policy.expand([""]) == frozenset()


def test_an_hr_user_reads_company_policies_without_listing_all_employees():
    policy = AccessPolicy(RULES, INHERITS)

    assert policy.can_read(("all_employees",), ["hr"])
    assert not policy.can_read(("hr",), ["all_employees"])   # inheritance goes one way
    assert not policy.can_read((), ["hr", "all_employees"])  # a chunk without groups: nobody


def test_a_query_admits_only_readable_chunks_of_its_country_or_company_wide():
    query = Query("q", frozenset({"all_employees"}), country="UA")

    assert query.admits(chunk(country="UA")) and query.admits(chunk(country=None))
    assert not query.admits(chunk(country="USA")) and not query.admits(chunk(access=("hr",), country="UA"))
    assert Query("q", frozenset({"all_employees"})).admits(chunk(country="USA"))   # no country: any


def test_rules_file_skips_comments(tmp_path: Path):
    path = tmp_path / "access.json"
    path.write_text(json.dumps({"_comment": "who may read what", "": ["all_employees"]}), encoding="utf-8")

    assert load_access_rules(path) == {"": ("all_employees",)}


def test_project_access_rules_are_valid():
    """No company or person names in it either: tests/test_no_private_data.py checks every committed file."""
    rules = load_access_rules(ROOT / "config" / "access.json")

    assert rules[""] == ("all_employees",)
    assert all(isinstance(g, tuple) and all(isinstance(x, str) for x in g) for g in rules.values())
