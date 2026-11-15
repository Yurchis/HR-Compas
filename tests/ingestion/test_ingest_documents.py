"""IngestDocuments: the incremental run, lineage (audit.jsonl), countries, and PII-free INFO logs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hr_compass.ingestion.application.ingest_documents import IngestDocuments
from hr_compass.ingestion.infrastructure.dataset_repo import DatasetRepository
from hr_compass.ingestion.infrastructure.extractors import SUPPORTED, extract
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.knowledge.infrastructure.files import load_chunks
from hr_compass.shared.tokens import TiktokenTokenizer

PAGE = "<html><body><main><h1>{title}</h1><p>{body}</p></main><footer>All rights reserved</footer></body></html>"
COUNTRIES = {"Usa": "USA", "UA": "UA"}


@pytest.fixture
def setup(tmp_path: Path):
    src, out = tmp_path / "src", tmp_path / "out"
    (src / "Usa" / "Policies").mkdir(parents=True)
    (src / "Usa" / "Policies" / "vacation.html").write_text(PAGE.format(title="Paid Vacation", body="24 days a year."),
                                                            encoding="utf-8")
    (src / "Usa" / "Policies" / "remote.html").write_text(PAGE.format(title="Remote Work", body="Two days a week."),
                                                          encoding="utf-8")
    (src / "notes.xlsx").write_bytes(b"not parsed")
    rules = {"": ("all_employees",)}

    def run(*, raw: bool = False, full: bool = False, rules_now: dict | None = None, extractor=extract,
            strategy: str = "headings"):
        use_case = IngestDocuments(DatasetRepository(out), extractor, SUPPORTED, AccessPolicy(rules_now or rules),
                                   TiktokenTokenizer(), chunk_tokens=120, countries=COUNTRIES, raw=raw,
                                   strategy=strategy)
        use_case.run(src, full=full)
        return json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    return src, out, run


def _events(out: Path, run_id: str) -> dict[str, str]:
    lines = (out / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return {e["source"]: e["event"] for e in map(json.loads, lines) if e["run"] == run_id and e["source"]}


VACATION, REMOTE = "Usa/Policies/vacation.html", "Usa/Policies/remote.html"


def test_first_run_ingests_everything_and_writes_outputs(setup):
    _src, out, run = setup

    manifest = run()

    assert _events(out, manifest["created_at"]) == {REMOTE: "ingested", VACATION: "ingested",
                                                    "notes.xlsx": "unsupported"}
    md = (out / "Usa" / "Policies" / "vacation.html.md").read_text(encoding="utf-8")
    assert md == "# Paid Vacation\n\n24 days a year.\n"
    records = load_chunks(out)
    assert {c.source for c in records} == {REMOTE, VACATION}
    assert {c.country for c in records} == {"USA"} and manifest["files"][VACATION]["country"] == "USA"


def test_unchanged_files_are_reused_with_the_same_chunks_and_dataset_version(setup):
    _src, out, run = setup
    first = run()
    chunks = load_chunks(out)
    extracted: list[Path] = []

    second = run(extractor=lambda p: extracted.append(p))  # must not be called

    assert extracted == []
    assert second["created_at"] != first["created_at"]
    assert second["dataset_version"] == first["dataset_version"]
    assert load_chunks(out) == chunks  # including the original ingested_at
    assert set(_events(out, second["created_at"]).values()) == {"unchanged"}


def test_a_changed_file_is_ingested_again_and_only_it(setup):
    src, out, run = setup
    first = run()
    (src / "Usa" / "Policies" / "vacation.html").write_text(PAGE.format(title="Paid Vacation", body="26 days a year."),
                                                            encoding="utf-8")

    second = run()

    assert second["dataset_version"] != first["dataset_version"]
    assert _events(out, second["created_at"]) == {VACATION: "changed", REMOTE: "unchanged", "notes.xlsx": "unchanged"}
    by_source = {c.source: c for c in load_chunks(out)}
    assert "26 days" in by_source[VACATION].text and by_source[VACATION].ingested_at == second["created_at"]


def test_a_removed_file_loses_its_chunks_and_its_text(setup):
    src, out, run = setup
    run()
    (src / "Usa" / "Policies" / "remote.html").unlink()

    manifest = run()

    assert _events(out, manifest["created_at"])[REMOTE] == "removed"
    assert not (out / "Usa" / "Policies" / "remote.html.md").exists()
    assert {c.source for c in load_chunks(out)} == {VACATION} and REMOTE not in manifest["files"]


def test_new_access_rules_apply_without_re_ingesting(setup):
    _src, out, run = setup
    first = run()

    second = run(rules_now={"": ("all_employees",), "Usa/Policies/remote": ("hr",)})

    assert set(_events(out, second["created_at"]).values()) == {"unchanged"}
    assert {c.source: c.access for c in load_chunks(out)}[REMOTE] == ("hr",)
    assert second["dataset_version"] != first["dataset_version"]  # the rules are an input too


def test_full_and_a_changed_text_setting_re_ingest_everything(setup):
    _src, out, run = setup
    run()

    full = run(full=True)
    raw = run(raw=True)

    assert set(_events(out, full["created_at"]).values()) == {"ingested", "unsupported"}
    assert set(_events(out, raw["created_at"]).values()) == {"ingested", "unsupported"}


def test_a_removed_file_loses_its_text_even_when_the_settings_change_and_orphan_texts_are_swept(setup):
    src, out, run = setup
    run()
    (src / "Usa" / "Policies" / "remote.html").unlink()
    orphan = out / "Usa" / "Old" / "Offer Letter Jane Doe.docx.md"   # left by an older run, in no manifest
    orphan.parent.mkdir(parents=True)
    orphan.write_text("salary", encoding="utf-8")

    manifest = run(strategy="fixed")   # extraction settings changed: nothing is reused

    events = _events(out, manifest["created_at"])
    assert events[REMOTE] == "removed" and events["Usa/Old/Offer Letter Jane Doe.docx"] == "removed"
    assert not (out / "Usa" / "Policies" / "remote.html.md").exists() and not orphan.exists()
    assert (out / "Usa" / "Policies" / "vacation.html.md").exists()


def test_runs_in_quick_succession_get_distinct_increasing_ids(setup):
    _src, _out, run = setup
    ids =[run(full=True)["created_at"] for _ in range(3)]   # faster than the Windows clock tick

    assert ids == sorted(set(ids)) and len(set(ids)) == 3


def test_another_chunking_strategy_re_ingests_and_fixed_windows_have_no_section(setup):
    _src, out, run = setup
    headings = run()
    assert {c.section for c in load_chunks(out)} == {"Paid Vacation", "Remote Work"}

    fixed = run(strategy="fixed")

    assert set(_events(out, fixed["created_at"]).values()) == {"ingested", "unsupported"}
    assert fixed["dataset_version"] != headings["dataset_version"]
    assert {c.section for c in load_chunks(out)} == {""}
    assert any("24 days a year." in c.text for c in load_chunks(out))


def test_missing_outputs_of_the_last_run_are_rebuilt(setup):
    _src, out, run = setup
    run()
    (out / "Usa" / "Policies" / "vacation.html.md").unlink()

    manifest = run()

    assert _events(out, manifest["created_at"])[VACATION] == "changed"
    assert (out / "Usa" / "Policies" / "vacation.html.md").exists()


def test_a_broken_file_is_reported_and_does_not_stop_the_batch(setup, caplog):
    _src, _out, run = setup

    def flaky(path: Path):
        if path.name == "remote.html":
            raise ValueError("boom")
        return extract(path)

    with caplog.at_level(logging.INFO, logger="hr_compass"):
        manifest = run(extractor=flaky)

    assert manifest["files"][REMOTE]["status"] == "error" and manifest["files"][VACATION]["status"] == "ok"
    [failed] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failed.doc != "-" and failed.fields["error_type"] == "ValueError"


def test_info_logs_name_documents_by_hash_never_by_path_or_title(tmp_path: Path, caplog):
    src = tmp_path / "src" / "UA" / "Job Offers"
    src.mkdir(parents=True)
    (src / "Offer Letter EU Jane Doe.html").write_text(PAGE.format(title="Offer for Jane Doe", body="Salary 700."),
                                                       encoding="utf-8")
    use_case = IngestDocuments(DatasetRepository(tmp_path / "out"), extract, SUPPORTED, AccessPolicy({"": ("hr",)}),
                               TiktokenTokenizer(), chunk_tokens=120, countries=COUNTRIES)

    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        use_case.run(tmp_path / "src")

    info = [r for r in caplog.records if r.levelno >= logging.INFO]
    rendered = " ".join(f"{r.getMessage()} {getattr(r, 'fields', '')} {r.doc}" for r in info)
    assert "Jane" not in rendered and "Offer Letter" not in rendered
    assert any(getattr(r, "fields", {}).get("step") == "chunk" for r in info)   # the steps are logged
    assert any("Jane" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)   # paths only at DEBUG
    assert {r.run_id for r in info} - {"-"}                                                       # every line has a run


def test_the_audit_log_keeps_every_run(setup):
    _src, out, run = setup
    first, second = run(), run()

    runs = {json.loads(line)["run"] for line in (out / "audit.jsonl").read_text(encoding="utf-8").splitlines()}

    assert {first["created_at"], second["created_at"]} <= runs
