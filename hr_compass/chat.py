"""Command-line chat: `python main.py` (interactive) or `python main.py "question"` (one-shot)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from hr_compass.config import ConfigError, Settings
from hr_compass.intake import IntakeError, load_intake_prompt
from hr_compass.knowledge import KnowledgeError, load_chunks
from hr_compass.logging_setup import configure_logging, resolve_log_file
from hr_compass.openrouter import OpenRouterClient
from hr_compass.pipeline import HRCompass, Reply
from hr_compass.prompts import PromptError, PromptTemplate
from hr_compass.resilient import LLMError, ResilientLLM
from hr_compass.retrieval import Reranker

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)
EXIT_WORDS = {"exit", "quit", "q", "вихід", "выход"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description="HR Compass: an HR assistant for employees.")
    p.add_argument("question", nargs="*", help="the question; without it the interactive mode starts")
    p.add_argument("--prompt", type=Path, default=ROOT / "prompts" / "v2_structured.md")
    p.add_argument("--intake-prompt", type=Path, default=ROOT / "prompts" / "intake_v2_en.md")
    p.add_argument("--no-intake", action="store_true", help="skip intake (language/scope/profile)")
    p.add_argument("--knowledge", type=Path, default=ROOT / "data" / "raw")
    p.add_argument("--config", type=Path, help="settings file (default: config/settings.toml)")
    p.add_argument("--model", help="model: an alias from [models] or an OpenRouter slug")
    p.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        help="pick the top-N sections with the reranker instead of the full context (default: [rerank].enabled)",
    )
    p.add_argument("--debug", action="store_true", help="show intake, model, tokens and cost; DEBUG-level log")
    p.add_argument("--log-file", type=Path, help="log file (default: logs/hr_compass.log; 'off' disables it)")
    return p


def format_reply(reply: Reply, *, debug: bool) -> str:
    lines = [reply.text]
    if reply.kind == "answer" and reply.sources:
        lines.append(f"Sources: {', '.join(f'[{s}]' for s in reply.sources)}")
    if debug:
        if reply.intake:
            lines.append(f"[intake] {reply.intake.model_dump_json()}")
        lines.append(
            f"[debug] kind={reply.kind} model={reply.model_used} confidence={reply.confidence} "
            f"input_tokens={reply.prompt_tokens} output_tokens={reply.completion_tokens} cost=${reply.cost_usd:.6f}"
        )
    return "\n".join(lines)


async def _interactive(bot: HRCompass, *, debug: bool) -> None:
    print("HR Compass. Ask a question (quit: exit).")
    logger.info("interactive session started")
    pending: str | None = None  # the question we asked a clarification for
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = (await loop.run_in_executor(None, input, "> ")).strip()
        except EOFError:
            logger.info("interactive session ended (EOF)")
            return
        if not line:
            continue
        if line.casefold() in EXIT_WORDS:
            logger.info("interactive session ended")
            return
        question, allow_clarification = line, True
        if pending:  # the line is the employee's reply to our clarifying question
            question, allow_clarification = f"{pending}\n(Employee's clarification: {line})", False
        try:
            reply = await bot.ask(question, allow_clarification=allow_clarification)
        except LLMError as exc:
            print(f"Model error: {exc}", file=sys.stderr)
            pending = None
            continue
        pending = question if reply.kind == "clarification" else None
        print(format_reply(reply, debug=debug))


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    if args.model:
        settings = replace(settings, model=settings.models.get(args.model, args.model))
    if args.rerank is not None:
        settings = replace(settings, rerank=replace(settings.rerank, enabled=args.rerank))
    prompt = PromptTemplate.from_file(args.prompt)
    intake_prompt = None if args.no_intake else load_intake_prompt(args.intake_prompt)
    chunks = load_chunks(args.knowledge)

    async with OpenRouterClient(settings) as client:
        reranker = Reranker(client, settings.rerank) if settings.rerank.enabled else None
        bot = HRCompass(ResilientLLM(client, settings), prompt, chunks, intake_prompt=intake_prompt, reranker=reranker)
        if args.question:
            try:
                reply = await bot.ask(" ".join(args.question), allow_clarification=False)
            except LLMError as exc:
                print(f"Model error: {exc}", file=sys.stderr)
                return 1
            print(format_reply(reply, debug=args.debug))
        else:
            await _interactive(bot, debug=args.debug)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.debug else logging.INFO
    configure_logging(
        console_level=logging.DEBUG if args.debug else logging.WARNING,  # the file always gets INFO+
        file_level=level,
        log_file=resolve_log_file(args.log_file),
    )
    load_dotenv(ROOT / ".env")
    logger.info("started args: model=%s intake=%s prompt=%s", args.model, not args.no_intake, args.prompt.name)
    try:
        return asyncio.run(_run(args))
    except (ConfigError, PromptError, IntakeError, KnowledgeError) as exc:
        logger.error("startup failed: %s", exc)
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
