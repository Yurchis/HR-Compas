"""Logging setup shared by the chat CLI and the evaluation CLI.

Console (stderr) and a rotating file. Secrets and raw question text never go above DEBUG:
INFO lines carry sizes, ids, models, tokens, cost and timings only.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = ROOT / "logs" / "hr_compass.log"
LOG_FILE_ENV = "HR_COMPASS_LOG_FILE"  # path; "" or "off" disables the file
FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"

# Correlates every log line of one question (or one evaluation sample) across modules.
request_id: ContextVar[str] = ContextVar("request_id", default="-")

_OWN = "_hr_compass_handler"


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def resolve_log_file(cli_value: Path | None) -> Path | None:
    """`--log-file` beats the env var, which beats the default; "off" disables the file."""
    if cli_value is not None:
        return None if str(cli_value).lower() == "off" else cli_value
    env = os.environ.get(LOG_FILE_ENV)
    if env is None:
        return DEFAULT_LOG_FILE
    return None if env.strip().lower() in ("", "off") else Path(env)


def configure_logging(
    *,
    console_level: int = logging.WARNING,
    file_level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Idempotent: replaces handlers from a previous call. Only the `hr_compass` logger tree is touched."""
    logger = logging.getLogger("hr_compass")
    for handler in [h for h in logger.handlers if getattr(h, _OWN, False)]:
        logger.removeHandler(handler)
        handler.close()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers[0].setLevel(console_level)
    problem: str | None = None
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        except OSError as exc:  # an unwritable log must never stop the bot
            problem = f"log file disabled: {exc}"
        else:
            file_handler.setLevel(file_level)
            handlers.append(file_handler)

    formatter = logging.Formatter(FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(_RequestIdFilter())
        setattr(handler, _OWN, True)
        logger.addHandler(handler)
    logger.setLevel(min(h.level for h in handlers))
    for noisy in ("httpx", "httpcore"):  # keep URLs and wire-level noise out of the logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if problem:
        logger.warning(problem)
