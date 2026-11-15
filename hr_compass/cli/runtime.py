"""Per-command logging setup, shared by single commands and by `hr-compass run`, whose steps each write their
own component log (ingest.log, index.log, eval.log, chat.log)."""

from __future__ import annotations

import argparse
import logging

from hr_compass.shared.logging import configure_logging, resolve_log_file
from hr_compass.shared.settings import Settings


def use_logs(component: str, args: argparse.Namespace, settings: Settings, console_level: int | None = None) -> None:
    """Point logging at `component`: its file (unless --log-file / HR_COMPASS_LOG_FILE says otherwise), DEBUG with
    -v / --debug, otherwise the command's console level."""
    debug = args.verbose or getattr(args, "debug", False)
    console = logging.DEBUG if debug else (console_level or getattr(args, "console_level", logging.INFO))
    configure_logging(component, console_level=console, file_level=logging.DEBUG if debug else logging.INFO,
                      log_file=resolve_log_file(component, args.log_file, settings.logging.dir),
                      max_bytes=settings.logging.max_bytes, backup_count=settings.logging.backup_count)
