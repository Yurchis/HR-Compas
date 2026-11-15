from __future__ import annotations

import itertools

import pytest

from hr_compass.ingestion.domain.chunking import ChunkDraft, chunk_by_headings, chunk_fixed, chunk_stats, is_heading
from hr_compass.shared.tokens import TiktokenTokenizer

SENTENCE = "Employees get twenty four calendar days of paid leave every year."  # ~13 tokens


@pytest.fixture(scope="module")
def tok() -> TiktokenTokenizer:
    return TiktokenTokenizer("cl100k_base")


def _paragraph(n: int) -> str:
    return " ".join([SENTENCE] * n)


def test_is_heading():
    assert is_heading("## Limits")
    assert is_heading("2. Eligibility")
    assert is_heading("3.1 Approval of requests")
    assert not is_heading("1. Open the Software Center.")       # a sentence: a list item
    assert not is_heading("1. Core hours\n2. Remote days")      # a list
    assert not is_heading("#hashtag")
    assert not is_heading("Plain paragraph")


def test_sections_and_their_path(tok):
    text = ("# Paid Vacation\n\n## New Hires\n\nAccrual starts on the hire date.\n\n"
            "## Advance Vacation\n\n### Approval\n\nThe manager approves.\n\n# Sick Leave\n\nUp to 4 months.")

    chunks = chunk_by_headings(text, tok, 120)

    assert [(c.section, c.text) for c in chunks] == [
        ("Paid Vacation > New Hires", "# Paid Vacation\n\n## New Hires\n\nAccrual starts on the hire date."),
        ("Paid Vacation > Advance Vacation > Approval", "## Advance Vacation\n\n### Approval\n\nThe manager approves."),
        ("Sick Leave", "# Sick Leave\n\nUp to 4 months."),
    ]
    assert chunks[1].path == ("Paid Vacation", "Advance Vacation", "Approval")


def test_numbered_titles_nest_under_markdown_headings(tok):
    chunks = chunk_by_headings("# Remote Work Policy\n\n1. Purpose\n\nWhy.\n\n2. Eligibility\n\nWho.", tok, 120)

    assert [c.path for c in chunks] == [("Remote Work Policy", "1. Purpose"), ("Remote Work Policy", "2. Eligibility")]


def test_whole_paragraphs_are_packed_up_to_max_tokens_and_never_cut(tok):
    paragraphs = [_paragraph(3) for _ in range(6)]  # ~40 tokens each
    chunks = chunk_by_headings("## Policy\n\n" + "\n\n".join(paragraphs), tok, 120)

    assert len(chunks) > 1
    assert all(tok.count(c.text) <= 120 for c in chunks)
    body = [p for c in chunks for p in c.text.split("\n\n") if not p.startswith("#")]
    assert body == paragraphs  # every paragraph whole, in order
    assert all(c.section == "Policy" for c in chunks)
    assert chunks[0].text.startswith("## Policy\n\n") and not chunks[1].text.startswith("##")


def test_a_long_paragraph_is_split_between_sentences(tok):
    chunks = chunk_by_headings(_paragraph(20), tok, 60)

    assert len(chunks) > 1
    assert all(c.text.startswith("Employees") and c.text.endswith("year.") for c in chunks)
    assert all(tok.count(c.text) <= 60 for c in chunks)


def test_a_long_table_is_split_between_rows_and_every_piece_keeps_the_header(tok):
    rows = [f"| vpn-{i}.example | Server number {i} in the region |" for i in range(30)]
    table = "\n".join(["| Server | Use for |", "| --- | --- |", *rows])

    chunks = chunk_by_headings(table, tok, 80)

    assert len(chunks) > 1
    for c in chunks:
        lines = c.text.split("\n")
        assert lines[:2] == ["| Server | Use for |", "| --- | --- |"]
        assert all(line.startswith("|") and line.endswith("|") for line in lines)
    assert [line for c in chunks for line in c.text.split("\n")[2:]] == rows
    assert chunk_stats(chunks, tok)["cut_tables"] == 0


def test_a_long_list_is_split_between_items_and_nested_items_stay_with_their_parent(tok):
    items = [f"{i}. Step number {i} of the onboarding checklist for new employees\n  - detail {i}"
             for i in range(1, 15)]

    chunks = chunk_by_headings("\n".join(items), tok, 60)

    assert len(chunks) > 1
    assert "\n".join(c.text for c in chunks) == "\n".join(items)
    assert all(c.text.split("\n")[0][0].isdigit() for c in chunks)


def test_trailing_headings_without_text_are_kept(tok):
    assert [c.text for c in chunk_by_headings("Intro.\n\n## Appendix", tok, 120)] == ["Intro.", "## Appendix"]


def test_by_headings_beats_the_fixed_baseline_on_mid_sentence_starts(tok):
    text = "\n\n".join(f"## Section {i}\n\n{_paragraph(4)}" for i in range(8))

    fixed, heading = chunk_stats(chunk_fixed(text, tok, 120), tok), chunk_stats(chunk_by_headings(text, tok, 120), tok)

    assert heading["starts_mid_sentence"] == 0
    assert fixed["starts_mid_sentence"] > 0


def test_fixed_windows_share_the_overlap_and_never_exceed_the_size(tok):
    text = _paragraph(20)

    chunks = chunk_fixed(text, tok, 50, overlap=10)

    tokens = [tok.encode(c.text) for c in chunks]
    assert len(chunks) > 1 and all(len(t) <= 50 for t in tokens) and all(not c.path for c in chunks)
    assert all(a[-10:] == b[:10] for a, b in itertools.pairwise(tokens))
    assert tok.decode(tokens[0] + [t for window in tokens[1:] for t in window[10:]]) == text   # nothing lost


def test_chunk_stats_reports_the_size_distribution_and_the_chunks_over_the_limit(tok):
    chunks = [ChunkDraft("a b", ("A",)), ChunkDraft(_paragraph(1), ("A",)), ChunkDraft(_paragraph(3))]

    s = chunk_stats(chunks, tok, limit=20)

    sizes = sorted(tok.count(c.text) for c in chunks)
    assert s["chunks"] == 3 and s["max_tokens"] == sizes[-1] and s["median_tokens"] == sizes[1]
    assert s["under_20"] == 2 and s["over_limit"] == 1 and s["no_section"] == 1
    assert "over_limit" not in chunk_stats(chunks, tok)
    assert chunk_stats([], tok)["chunks"] == 0


def test_a_draft_section_is_its_heading_path():
    assert ChunkDraft("x", ("A", "B")).section == "A > B" and ChunkDraft("x").section == ""
