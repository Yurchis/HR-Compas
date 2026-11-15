from __future__ import annotations

import hashlib

import pytest

from hr_compass.ingestion.domain.dedup import canonical, content_hash, jaccard, near_duplicates, shingles

TEXT = "# Paid vacation\n\nEmployees get 24 calendar days a year."


@pytest.mark.parametrize("variant", [
    TEXT.replace("\n", "\r\n"),                      # Windows line endings
    TEXT.replace("\n", "\r"),                        # old Mac line endings
    "  " + TEXT.replace(" ", "   ") + " \n\n",       # extra and trailing spaces
    TEXT.replace(" ", "\t"),                         # tabs
    TEXT.replace("\n\n", "\n\n\n\n"),                # more blank lines
    TEXT.replace("Employees get", "Employees\nget"), # a line wrapped elsewhere
    TEXT.replace("\n\n", "\f"),                      # a page break
    "﻿" + TEXT.replace("24", "24​"),       # BOM and zero-width space
    TEXT.replace(" ", " "),                     # non-breaking spaces
    TEXT.replace("24", "２４"),                       # full-width digits (NFKC)
])
def test_same_content_gives_the_same_hash(variant):
    assert content_hash(variant) == content_hash(TEXT)


@pytest.mark.parametrize("other", [
    TEXT.replace("24", "25"),                        # a different number of days
    TEXT.lower(),                                    # case is content
    TEXT.replace("# Paid", "## Paid"),               # structure is content
    TEXT.replace("Employees get", "Employeesget"),   # removed space joins two words
])
def test_different_content_gives_a_different_hash(other):
    assert content_hash(other) != content_hash(TEXT)


def test_hash_is_sha256_of_the_canonical_form():
    assert canonical(" a\r\n\tb ") == "a b"
    assert content_hash(" a\r\n\tb ") == hashlib.sha256(b"a b").hexdigest()


# ---------------------------------------------------------------- near duplicates

POLICY = (
    "Employees are eligible for twenty four calendar days of paid annual leave. Vacation accrues "
    "proportionally throughout the calendar year and is calculated daily based on continuous employment. "
    "Requests are submitted in BambooHR at least two weeks before the planned start date. "
    "Unused vacation does not carry over to the following calendar year and is paid through payroll. "
    "Advance vacation requires approval from the direct manager and Human Resources."
)


def test_shingles_are_word_runs_ignoring_case_punctuation_and_markup():
    assert shingles("# One, two THREE four five six!") == {("one", "two", "three", "four", "five"),
                                                         ("two", "three", "four", "five", "six")}
    assert shingles("Too short") == {("too", "short")}
    assert shingles(" -- ") == set()


def test_jaccard():
    assert jaccard({1, 2, 3}, {2, 3, 4}) == 0.5
    assert jaccard(set(), set()) == 0.0


def test_a_new_version_of_a_document_is_a_near_duplicate_and_unrelated_ones_are_not():
    docs = {
        "policy_v1.pdf": POLICY,
        "policy_v2.docx": POLICY.replace("Human Resources.", "Human Resources. Approvals take one day."),
        "vpn.docx": "Install the VPN client from the Software Center and sign in with your company e-mail.",
    }

    [(a, b, score)] = near_duplicates(docs)

    assert (a, b) == ("policy_v1.pdf", "policy_v2.docx")
    assert 0.8 <= score < 1.0


def test_every_pair_is_compared_once_and_the_most_similar_comes_first():
    v2 = POLICY.replace("two weeks", "three weeks")
    v3 = v2.replace("calendar year and is paid", "year and is paid")
    pairs = near_duplicates([("v1", POLICY), ("v2", v2), ("v3", v3)], threshold=0.5)

    assert [(a, b) for a, b, _ in pairs] == [("v2", "v3"), ("v1", "v2"), ("v1", "v3")]
    assert [s for *_, s in pairs] == sorted((s for *_, s in pairs), reverse=True)


def test_exact_copies_score_one_and_empty_documents_never_match():
    pairs = near_duplicates({"a": POLICY, "a copy": POLICY.upper(), "scan1": "", "scan2": " "})

    assert pairs == [("a", "a copy", 1.0)]
