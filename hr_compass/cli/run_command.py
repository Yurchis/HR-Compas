"""`hr-compass run`: the whole pipeline in one command, from the documents to the chat.

    [1/3] ingest   documents -> chunks; unchanged files are reused (seconds on a re-run)
    [2/3] index    chunks -> vectors (cached) -> index; stops when the access check fails
          --check  + lint the testset and gate the search quality; stops when either fails
    [3/3] chat     the bot (one question, or interactive); --no-chat stops before it

Every step writes its own log (logs/ingest.log, index.log, eval.log, chat.log); the console shows the steps' summaries
and warnings (-v for everything).
"""

from __future__ import annotations

import argparse
import logging

from hr_compass.cli import chat_command, data_commands, eval_commands
from hr_compass.cli.container import Container
from hr_compass.cli.runtime import use_logs


def _step(n: int, total: int, title: str) -> None:
    print(f"\n[{n}/{total}] {title}")


def _checks(c: Container, args: argparse.Namespace) -> int:
    """Lint the testset, then gate the search quality against the saved baseline (skipped when there is none)."""
    use_logs("eval", args, c.settings, logging.WARNING)
    if eval_commands.lint_command(c, args) != 0:
        print("the testset does not match the documents: fix it (hr-compass eval lint) or run without --check")
        return 1
    baseline = c.settings.eval.results_dir / eval_commands.RETRIEVAL_BASELINE
    if not baseline.exists():
        print(f"no search baseline ({baseline.name}): gate skipped; save one with "
              "`hr-compass eval retrieval --save-baseline`")
        return 0
    gate_args = argparse.Namespace(**vars(args), only=None, save_baseline=False, gate=True)
    return eval_commands.retrieval_command(c, gate_args)


def run(c: Container, args: argparse.Namespace) -> int:
    if not args.no_chat:
        c.settings.require_api_key()   # say it now, not after the documents were processed
    total = 3
    _step(1, total, "ingest: documents -> chunks")
    use_logs("ingest", args, c.settings, logging.WARNING)
    if data_commands.ingest(c, argparse.Namespace(src=None, full=args.full, raw=False)) != 0:
        print("stopped: nothing to ingest")
        return 1

    _step(2, total, "index: chunks -> vectors -> search index")
    use_logs("index", args, c.settings, logging.WARNING)
    if data_commands.index(c, args) != 0:
        print("stopped: the access check failed")
        return 1

    if args.check:
        print("\n      checks: testset lint + search quality gate")
        if _checks(c, args) != 0:
            print("stopped: a check failed")
            return 1

    if args.no_chat:
        print("\nready: `make run` (python main.py) to ask questions")
        return 0
    _step(3, total, "chat")
    use_logs("chat", args, c.settings, logging.WARNING)
    return chat_command.chat(c, args)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("run", help="everything in one command: ingest -> index (-> checks) -> chat")
    p.add_argument("question", nargs="*", help="ask one question at the end; without it the chat is interactive")
    p.add_argument("--groups", help="comma-separated groups of the user (default: [access].default_groups)")
    p.add_argument("--country", choices=("USA", "UA", "Costa Rica"), help="the employee's country, if known")
    p.add_argument("--model", help="an alias from [models] or an OpenRouter slug")
    p.add_argument("--no-intake", action="store_true", help="skip the intake step")
    p.add_argument("--debug", action="store_true", help="show intake, retrieval, model, tokens and cost")
    p.add_argument("--full", action="store_true", help="re-ingest every file, not only the changed ones")
    p.add_argument("--check", action="store_true", help="lint the testset and gate the search quality before the chat")
    p.add_argument("--no-chat", action="store_true", help="prepare the data (and check it) without starting the chat")
    p.set_defaults(func=run, component="run", console_level=logging.WARNING)
