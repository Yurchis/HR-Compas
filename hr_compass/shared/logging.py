"""Logging for every component: JSON lines in `logs/<component>.log`, readable text on the console.

    configure_logging("ingest", console_level=logging.INFO)
    with log_context(run_id=run, doc=doc_ref(raw_hash)):
        logger.info("extracted", extra=kv(step="extract", ms=12, chars=2521))

A file line: {"ts", "level", "logger", "component", "run_id", "request_id", "doc", "msg", ...fields}, so
"what happened to document X in run Y" is one `jq 'select(.run_id==Y and .doc==X)'`.
Each component has its own rotating file: a verbose ingest run never pushes the chat log out.

Privacy: secrets are never logged; question texts, chunk texts, document paths and titles (they hold people's
names) only at DEBUG. INFO lines carry sizes, ids, hash prefixes (`shared.refs`), scores, tokens, cost, timings.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from hr_compass.shared.paths import ROOT

ROOT_LOGGER = "hr_compass"
DEFAULT_LOG_DIR = ROOT / "logs"
LOG_FILE_ENV = "HR_COMPASS_LOG_FILE"   # a path overrides every component's file; "" or "off" disables files
CONTEXT_FIELDS = ("run_id", "request_id", "doc")
TEXT_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s%(doc_part)s] %(name)s: %(message)s"

_context: dict[str, ContextVar[str]] = {name: ContextVar(name, default="-") for name in CONTEXT_FIELDS}
_component: ContextVar[str] = ContextVar("component", default="-")
_OWN = "_hr_compass_handler"


def kv(**fields: Any) -> dict[str, dict[str, Any]]:
    """Structured fields for one record: logger.info("msg", extra=kv(step="chunk", ms=5))."""
    return {"fields": fields}


@contextmanager
def log_context(**values: str) -> Iterator[None]:
    """Set run_id / request_id / doc for every record logged inside (also in awaited coroutines)."""
    unknown = set(values) - set(CONTEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown log context field(s): {sorted(unknown)}")
    tokens = [(_context[name], _context[name].set(value)) for name, value in values.items()]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current(name: str) -> str:
    return _context[name].get()


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for name in CONTEXT_FIELDS:
            setattr(record, name, _context[name].get())
        record.component = _component.get()
        doc = record.doc
        record.doc_part = f" doc={doc}" if doc != "-" else ""
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "component": getattr(record, "component", "-"),
            **{name: getattr(record, name, "-") for name in CONTEXT_FIELDS},
            "msg": record.getMessage(),
        }
        line.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Console: the message, then the structured fields as key=value."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        fields = getattr(record, "fields", None)
        return f"{text} {' '.join(f'{k}={v}' for k, v in fields.items())}" if fields else text


def resolve_log_file(component: str, cli_value: Path | None = None, log_dir: Path = DEFAULT_LOG_DIR) -> Path | None:
    """`--log-file` beats the env var, which beats logs/<component>.log; "off" disables the file."""
    if cli_value is not None:
        return None if str(cli_value).lower() == "off" else cli_value
    env = os.environ.get(LOG_FILE_ENV)
    if env is not None:
        return None if env.strip().lower() in ("", "off") else Path(env)
    return log_dir / f"{component}.log"


def configure_logging(component: str, *, console_level: int = logging.WARNING, file_level: int = logging.INFO,
                      log_file: Path | None = None, max_bytes: int = 5_000_000, backup_count: int = 5) -> None:
    """Idempotent: replaces the handlers of a previous call. Only the `hr_compass` logger tree is touched."""
    _component.set(component)
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in [h for h in logger.handlers if getattr(h, _OWN, False)]:
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(TextFormatter(TEXT_FORMAT))
    handlers: list[logging.Handler] = [console]
    problem: str | None = None
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count,
                                               encoding="utf-8")
        except OSError as exc:  # an unwritable log must never stop the tool
            problem = f"log file disabled: {exc}"
        else:
            file_handler.setLevel(file_level)
            file_handler.setFormatter(JsonFormatter())
            handlers.append(file_handler)
    for handler in handlers:
        handler.addFilter(_ContextFilter())
        setattr(handler, _OWN, True)
        logger.addHandler(handler)
    logger.setLevel(min(h.level for h in handlers))
    for noisy in ("httpx", "httpcore"):  # keep URLs and wire-level noise out of the logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if problem:
        logger.warning(problem)


def remove_handlers() -> None:
    """For tests: drop the handlers `configure_logging` added."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in [h for h in logger.handlers if getattr(h, _OWN, False)]:
        logger.removeHandler(handler)
        handler.close()


def context_filter() -> logging.Filter:
    """The filter that adds run_id / request_id / doc to records (for pytest's caplog handler)."""
    return _ContextFilter()
