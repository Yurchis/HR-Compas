"""Structured logging: JSON lines per component, context fields, idempotent setup, no crash on a bad file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hr_compass.shared.logging import LOG_FILE_ENV, configure_logging, current, kv, log_context, resolve_log_file
from hr_compass.shared.refs import chunk_ref, doc_ref

logger = logging.getLogger("hr_compass.test")


def _lines(path: Path) -> list[dict]:
    for handler in logging.getLogger("hr_compass").handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_component_has_its_own_file_and_env_and_flag_override_it(monkeypatch, tmp_path):
    monkeypatch.delenv(LOG_FILE_ENV, raising=False)
    assert resolve_log_file("ingest", log_dir=tmp_path) == tmp_path / "ingest.log"
    assert resolve_log_file("chat", log_dir=tmp_path) == tmp_path / "chat.log"
    monkeypatch.setenv(LOG_FILE_ENV, str(tmp_path / "env.log"))
    assert resolve_log_file("chat") == tmp_path / "env.log"
    assert resolve_log_file("chat", tmp_path / "cli.log") == tmp_path / "cli.log"
    assert resolve_log_file("chat", Path("off")) is None
    monkeypatch.setenv(LOG_FILE_ENV, "off")
    assert resolve_log_file("chat") is None


def test_file_lines_are_json_with_context_and_fields(tmp_path):
    log = tmp_path / "ingest.log"
    configure_logging("ingest", log_file=log)

    with log_context(run_id="run-1", doc="abc123def456"):
        logger.info("chunked", extra=kv(step="chunk", chunks=6, ms=12))
    logger.warning("outside")

    first, second = _lines(log)
    assert first["msg"] == "chunked" and first["component"] == "ingest" and first["level"] == "INFO"
    assert (first["run_id"], first["doc"], first["request_id"]) == ("run-1", "abc123def456", "-")
    assert (first["step"], first["chunks"], first["ms"]) == ("chunk", 6, 12)
    assert second["run_id"] == "-" and second["doc"] == "-"   # the context is reset after the block


def test_the_context_is_restored_after_nested_blocks():
    with log_context(run_id="outer"):
        with log_context(run_id="inner", request_id="q1"):
            assert (current("run_id"), current("request_id")) == ("inner", "q1")
        assert (current("run_id"), current("request_id")) == ("outer", "-")
    with pytest.raises(ValueError, match="unknown"), log_context(user="x"):
        pass


def test_configure_is_idempotent_and_levels_apply(tmp_path):
    log = tmp_path / "x.log"
    configure_logging("eval", log_file=log)
    configure_logging("eval", log_file=log, file_level=logging.WARNING)

    logger.info("dropped")
    logger.warning("kept")

    assert [line["msg"] for line in _lines(log)] == ["kept"]   # one file handler, the new level
    own = [h for h in logging.getLogger("hr_compass").handlers if getattr(h, "_hr_compass_handler", False)]
    assert len(own) == 2   # console + file


def test_an_unwritable_log_file_does_not_break_startup(tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="hr_compass"):
        configure_logging("chat", log_file=blocker / "sub" / "x.log")
    assert "log file disabled" in caplog.text


def test_exceptions_are_written_into_the_json_line(tmp_path):
    log = tmp_path / "x.log"
    configure_logging("ingest", log_file=log)
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")

    [line] = _lines(log)
    assert "ValueError: boom" in line["exc"]


def test_refs_hide_paths_behind_hash_prefixes():
    assert doc_ref("a" * 64) == "a" * 12 and chunk_ref("b" * 64, 105) == "b" * 12 + "#105"
