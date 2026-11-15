from __future__ import annotations

from hr_compass.ingestion.domain.normalize import normalize, unwrap

BODY = "This policy explains who may work remotely, how remote days are approved and which"


def test_unicode_line_endings_and_invisible_characters():
    text = "﻿ＶＰＮ setup\r\nAsk the ﬁrst​ line.\r\n"

    assert normalize(text) == "VPN setup\nAsk the first line."


def test_running_headers_and_page_numbers_are_removed_but_kept_once():
    page = "It Company — Internal\nEffective 2026-01-15\n## Section {s}\nText of section {s}.\nPage {n} of 3"
    text = "\f".join(page.format(n=n, s=s) for n, s in ((1, 2), (2, 5), (3, 6)))

    assert normalize(text) == (
        "It Company — Internal\nEffective 2026-01-15\n\n## Section 2\nText of section 2.\n\n"
        "## Section 5\nText of section 5.\n\n"
        "## Section 6\nText of section 6."
    )


def test_a_running_line_with_a_page_counter_is_dropped_but_numbered_content_is_not():
    text = "\f".join(f"Rule {r}.\nConfidential - p. {n + 4}" for n, r in ((1, 7), (2, 3), (3, 9)))

    assert normalize(text) == "Rule 7.\nConfidential - p. 5\nRule 3.\nRule 9."


def test_page_of_numbers_are_removed_anywhere_and_bare_numbers_only_at_page_edges():
    text = "Intro.\n2 / 5\nThe office has\n3\nfloors.\n4\fNext page.\n5"

    assert normalize(text) == "Intro.\nThe office has\n3\nfloors.\nNext page."


def test_words_hyphenated_across_lines_are_joined():
    assert normalize(f"{BODY} secur-\nity rules apply.") == f"{BODY} security rules apply."
    assert normalize("Policy for COVID-\n19 cases.") == "Policy for COVID-\n19 cases."  # not a broken word


def test_spaces_are_collapsed_but_list_indent_is_kept():
    text = "Hours  of\twork:   \n1. Core   hours\n  - Kyiv  time\n\n\n\nEnd."

    assert normalize(text) == "Hours of work:\n1. Core hours\n  - Kyiv time\n\nEnd."


def test_unwrap_joins_lines_broken_inside_a_sentence_across_pages():
    text = f"## Purpose\n{BODY}\nsecurity rules apply to laptops.\fDuring martial law employees may take" \
           f" vacation in increments of\nfour hours.\n- one\n- two\n| a | b |\n| c | d |"

    assert normalize(text) == (
        f"## Purpose\n{BODY} security rules apply to laptops.\n"
        "During martial law employees may take vacation in increments of four hours.\n"
        "- one\n- two\n| a | b |\n| c | d |"
    )


def test_a_heading_always_starts_a_block():
    assert normalize("End of page one.\f## Next section\nText.") == "End of page one.\n\n## Next section\nText."


def test_unwrap_keeps_short_lines_headings_and_finished_sentences():
    text = f"Title line\nNext line\n{BODY}.\nNew sentence.\n{BODY}\n## Heading"

    assert unwrap(text) == text


def test_normalize_is_idempotent():
    text = f"It Co\n{BODY}\nsecur-\nity.\nPage 1 of 2\fIt Co\n- item\nPage 2 of 2"

    once = normalize(text)
    assert normalize(once) == once
