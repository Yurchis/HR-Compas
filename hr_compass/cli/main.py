"""hr-compass: the whole pipeline from documents to answers, one command.

    hr-compass run ["question"]        everything below in order, then the chat (python main.py)
    hr-compass ingest                  documents -> chunks (incremental)          logs/ingest.log
    hr-compass index                   chunks -> vectors -> index, access check   logs/index.log
    hr-compass search "question"       the top hits of every search configuration logs/search.log
    hr-compass chat ["question"]       the HR bot (RAG)                           logs/chat.log
    hr-compass eval lint|retrieval|pairs|answers|calibrate                        logs/eval.log
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from hr_compass.cli import chat_command, data_commands, eval_commands, run_command
from hr_compass.cli.container import Container
from hr_compass.cli.runtime import use_logs
from hr_compass.evaluation.domain.retrieval_metrics import QuestionError
from hr_compass.shared.logging import kv
from hr_compass.shared.paths import ROOT
from hr_compass.shared.prompts import PromptError
from hr_compass.shared.settings import ConfigError, Settings

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hr-compass", description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--config", type=Path, help="settings file (default: config/settings.toml)")
    p.add_argument("--log-file", type=Path, help="log file (default: logs/<component>.log; 'off' disables)")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logs on the console and in the file")
    sub = p.add_subparsers(dest="command", required=True)
    run_command.add_parser(sub)
    data_commands.add_parsers(sub)
    chat_command.add_parser(sub)
    eval_commands.add_parser(sub)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        settings = Settings.load(args.config)
        use_logs(args.component, args, settings)
        logger.info("command started", extra=kv(command=args.command, fingerprint=settings.fingerprint()[:12]))
        return args.func(Container(settings), args)
    except (ConfigError, PromptError, QuestionError, FileNotFoundError) as exc:
        logger.error("startup failed: %s", exc)
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
