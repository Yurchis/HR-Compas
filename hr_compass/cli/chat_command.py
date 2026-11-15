"""`hr-compass chat`: one question, or an interactive session that keeps the last turns for follow-ups."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Mapping
from dataclasses import replace

from hr_compass.assistant.application.ask_question import AskQuestion, Turn
from hr_compass.assistant.domain.reply import Reply
from hr_compass.assistant.infrastructure.resilient_llm import ResilientLLM
from hr_compass.cli.container import Container
from hr_compass.knowledge.domain.chunk import ChunkRecord
from hr_compass.shared.llm import LLMError
from hr_compass.shared.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)
EXIT_WORDS = {"exit", "quit", "q", "вихід", "выход"}


def format_reply(reply: Reply, chunks: Mapping[str, ChunkRecord], *, debug: bool) -> str:
    lines = [reply.text]
    if reply.cited:
        lines.append("Sources:")
        lines += [f"  [{i}] {chunks[cid].title} — {chunks[cid].section or 'no section'}" if cid in chunks
                  else f"  [{i}] {cid}" for i, cid in enumerate(reply.cited, start=1)]
    if debug:
        if reply.intake:
            lines.append(f"[intake] {reply.intake.model_dump_json()}")
        lines.append(f"[retrieved] {len(reply.retrieved)} chunks, {reply.context_tokens} context tokens; "
                     f"query: {reply.query!r}")
        lines.append(f"[debug] kind={reply.kind} found={reply.found} model={reply.model_used} "
                     f"confidence={reply.confidence} input_tokens={reply.prompt_tokens} "
                     f"output_tokens={reply.completion_tokens} cost=${reply.cost_usd:.6f}")
    return "\n".join(lines)


async def _interactive(bot: AskQuestion, c: Container, args: argparse.Namespace, groups: list[str]) -> None:
    print("HR Compass. Ask a question (quit: exit).")
    logger.info("interactive session started")
    history: list[Turn] = []
    pending: str | None = None  # the question we asked a clarification for
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = (await loop.run_in_executor(None, input, "> ")).strip()
        except EOFError:
            break
        if not line:
            continue
        if line.casefold() in EXIT_WORDS:
            break
        question, allow_clarification = line, True
        if pending:  # the line is the employee's reply to our clarifying question
            question, allow_clarification = f"{pending}\n(Employee's clarification: {line})", False
        try:
            reply = await bot.ask(question, groups=groups, country=args.country,
                                  history=history[-c.settings.rag.history_turns:] if history else (),
                                  allow_clarification=allow_clarification)
        except LLMError as exc:
            print(f"Model error: {exc}", file=sys.stderr)
            pending = None
            continue
        pending = question if reply.kind == "clarification" else None
        if reply.kind == "answer":
            history.append((question, reply.text))
        print(format_reply(reply, c.chunks_by_id, debug=args.debug))
    logger.info("interactive session ended")


async def _run(c: Container, args: argparse.Namespace) -> int:
    settings = c.settings
    if args.model:
        settings = replace(settings, model=settings.resolve_model(args.model))
    groups = c.user_groups(args.groups)
    async with OpenRouterClient(settings) as client:
        bot = c.ask_question(ResilientLLM(client, settings), intake=False if args.no_intake else None)
        if not args.question:
            await _interactive(bot, c, args, groups)
            return 0
        try:
            reply = await bot.ask(" ".join(args.question), groups=groups, country=args.country,
                                  allow_clarification=False)
        except LLMError as exc:
            print(f"Model error: {exc}", file=sys.stderr)
            return 1
        print(format_reply(reply, c.chunks_by_id, debug=args.debug))
    return 0


def chat(c: Container, args: argparse.Namespace) -> int:
    c.settings.require_api_key()   # a clean configuration error before anything is loaded
    if not c.chunks:   # no chunks.jsonl at all raises a clear FileNotFoundError; an empty one would answer nothing
        print(f"no documents are indexed in {c.settings.ingest.output_dir}: build the data first with "
              "`make pipeline` (python main.py run)", file=sys.stderr)
        return 2
    return asyncio.run(_run(c, args))


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("chat", help="ask the HR bot (interactive without a question)")
    p.add_argument("question", nargs="*", help="the question; without it the interactive mode starts")
    p.add_argument("--groups", help="comma-separated groups of the user (default: [access].default_groups)")
    p.add_argument("--country", choices=("USA", "UA", "Costa Rica"), help="the employee's country, if known")
    p.add_argument("--model", help="an alias from [models] or an OpenRouter slug")
    p.add_argument("--no-intake", action="store_true", help="skip the intake step")
    p.add_argument("--debug", action="store_true", help="show intake, retrieval, model, tokens and cost")
    p.set_defaults(func=chat, component="chat", console_level=logging.WARNING)
