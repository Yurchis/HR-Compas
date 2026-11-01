"""CLI: run a prompt over a samples file through OpenRouter and save results.

Every sample goes through the same pipeline as the chat (intake -> context -> answer), with the sample's
country / sub_company as the known employee profile. `--no-intake` calls the answer model directly.

Usage:
    python -m hr_compass.evaluate --prompt prompts/v2_structured.md --samples data/golden_set.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from hr_compass.config import ConfigError, GenerationConfig, Settings
from hr_compass.intake import IntakeError, load_intake_prompt
from hr_compass.knowledge import KnowledgeError, load_chunks
from hr_compass.logging_setup import configure_logging, resolve_log_file
from hr_compass.openrouter import OpenRouterClient
from hr_compass.prompts import PromptError, PromptTemplate
from hr_compass.resilient import ResilientLLM
from hr_compass.retrieval import Reranker
from hr_compass.runner import EvaluationRunner, SampleResult, result_to_dict, summarize
from hr_compass.samples import SampleError, load_samples

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("hr_compass.evaluate")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hr_compass.evaluate", description=__doc__.split("\n")[0])
    p.add_argument("--prompt", type=Path, required=True, help="prompt template file (with {{context}})")
    p.add_argument("--intake-prompt", type=Path, default=ROOT / "prompts" / "intake_v2_en.md")
    p.add_argument(
        "--no-intake",
        action="store_true",
        help="skip intake: call the answer model directly (every reply is an 'answer'); "
        "also implied when [structured_output] is disabled",
    )
    p.add_argument("--samples", type=Path, default=ROOT / "data" / "golden_set.jsonl")
    p.add_argument("--knowledge", type=Path, default=ROOT / "data" / "raw", help="dir with chunk JSON files")
    p.add_argument("--output-dir", type=Path, default=ROOT / "results" / "runs")
    p.add_argument("--config", type=Path, help="settings file (default: config/settings.toml)")
    p.add_argument("--model", help="override [openrouter].model (alias from [models] or an OpenRouter slug)")
    p.add_argument("--models", help="comma-separated aliases/slugs to compare one by one (fallback disabled)")
    p.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        help="select top-N chunks with the reranker instead of full context (default: [rerank].enabled)",
    )
    p.add_argument("--limit", type=int, help="only run the first N samples")
    p.add_argument("--log-file", type=Path, help="log file (default: logs/hr_compass.log; 'off' disables)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def write_run(
    output_dir: Path,
    *,
    model: str,
    prompt: PromptTemplate,
    samples_path: Path,
    results: Sequence[SampleResult],
    rerank: str | None = None,  # rerank model slug; None = full context
    generation: GenerationConfig | None = None,
    intake: str | None = None,  # intake prompt name; None = intake skipped
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / f"{stamp}_{_slug(model)}_{_slug(prompt.name)}{'_rerank' if rerank else ''}"
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(result_to_dict(r), ensure_ascii=False) + "\n")
    meta = {
        "timestamp": stamp,
        "model": model,
        "prompt": prompt.name,
        "samples": str(samples_path),
        "rerank": rerank,
        "intake": intake,
        "generation": asdict(generation) if generation else None,  # temperature/top_p/max_tokens of this run
        "summary": summarize(results),
    }
    (run_dir / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def comparison_table(rows: Sequence[dict]) -> str:
    """Markdown table: one row per run, ready to paste into REPORT.md."""
    lines = [
        "| Model | Prompt version | Sampling | Price, $/1M (in/out) | Correct, % | Reply type, % "
        "| Input tokens | Output tokens | p50, s | p95, s | Succeeded | Run cost, $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def pct(value: float | None, passed: int | None, checked: int | None) -> str:
        return "—" if value is None else f"{value}% ({passed}/{checked})"

    def num(value: float | None) -> str:
        return "—" if value is None else str(value)

    def thousands(value: int) -> str:
        return f"{value:,}".replace(",", " ")  # 265 540 — readable token counts

    for r in rows:
        s = r["summary"]
        model =f"{r['model']} + rerank" if r.get("rerank") else r["model"]
        gen = r.get("generation")
        sampling = f"temperature={gen['temperature']}, top_p={gen['top_p']}" if gen else "—"
        price = r.get("price")
        price_text = f"{price[0]} / {price[1]}" if price else "—"
        accuracy = pct(s.get("accuracy_pct"), s.get("keyword_passed"), s.get("keyword_checked"))
        kind_accuracy = pct(s.get("kind_accuracy_pct"), s.get("kind_passed"), s.get("kind_checked"))
        prompt = r.get("prompt", "—") + (f" + {r['intake']}" if r.get("intake") else "")
        lines.append(
            f"| {model} | {prompt} | {sampling} | {price_text} | {accuracy} | {kind_accuracy} "
            f"| {thousands(s['prompt_tokens'])} | {thousands(s['completion_tokens'])} | {num(s['latency_p50_s'])} "
            f"| {num(s['latency_p95_s'])} | {s['succeeded']}/{s['total']} | {s['cost_usd']} |"
        )
    return "\n".join(lines) + "\n"


def write_comparison(output_dir: Path, *, prompt: PromptTemplate, rows: Sequence[dict]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = output_dir / f"{stamp}_compare_{_slug(prompt.name)}"
    base.with_suffix(".json").write_text(json.dumps(list(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    md = base.with_suffix(".md")
    md.write_text(f"# Model comparison, prompt `{prompt.name}`\n\n{comparison_table(rows)}", encoding="utf-8")
    return md


def resolve_models(settings: Settings, names: Sequence[str]) -> list[str]:
    """Aliases from `[models]` become slugs; anything else is taken as a raw OpenRouter slug."""
    return list(dict.fromkeys(settings.models.get(n, n) for n in names))


def resolve_intake(settings: Settings, args: argparse.Namespace) -> tuple[str | None, str | None]:
    """(intake prompt text, its name) or (None, None) when intake is skipped."""
    if args.no_intake:
        return None, None
    if not settings.structured_output.enabled:  # intake returns a validated JSON verdict
        logger.warning("intake skipped: it needs [structured_output].enabled = true (every reply will be an 'answer')")
        return None, None
    return load_intake_prompt(args.intake_prompt), args.intake_prompt.stem


async def _evaluate(settings: Settings, args: argparse.Namespace, prompt: PromptTemplate, samples, chunks) -> dict:
    intake_prompt, intake_name = resolve_intake(settings, args)
    logger.info(
        "models=%s prompt=%s intake=%s samples=%d chunks=%d structured=%s rerank=%s",
        " -> ".join(settings.model_chain),
        prompt.name,
        intake_name,
        len(samples),
        len(chunks),
        settings.structured_output.enabled,
        settings.rerank.enabled,
    )
    async with OpenRouterClient(settings) as client:
        llm = ResilientLLM(client, settings)
        reranker = Reranker(client, settings.rerank) if settings.rerank.enabled else None
        runner = EvaluationRunner(
            llm, prompt, chunks, concurrency=settings.concurrency, reranker=reranker, intake_prompt=intake_prompt
        )
        results = await runner.run(samples)

    run_dir = write_run(
        args.output_dir,
        model=settings.model,
        prompt=prompt,
        samples_path=args.samples,
        results=results,
        rerank=settings.rerank.model if settings.rerank.enabled else None,
        generation=settings.generation,
        intake=intake_name,
    )
    logger.info("saved to %s", run_dir)
    row = {
        "model": settings.model,
        "prompt": prompt.name,
        "intake": intake_name,
        "generation": asdict(settings.generation),
        "price": settings.pricing.get(settings.model),  # $/1M (input, output); None if not in [pricing]
        "rerank": settings.rerank.model if settings.rerank.enabled else None,
        "run_dir": str(run_dir),
        "summary": summarize(results),
    }
    (run_dir / "table.md").write_text(comparison_table([row]), encoding="utf-8")
    return row


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    prompt = PromptTemplate.from_file(args.prompt)
    samples = load_samples(args.samples)[: args.limit]
    chunks = load_chunks(args.knowledge)
    if args.rerank is not None:
        settings = replace(settings, rerank=replace(settings.rerank, enabled=args.rerank))

    if args.models:
        # Compare models one by one; fallback is off so a model is never silently replaced by another.
        names = [n.strip() for n in args.models.split(",") if n.strip()]
        if not names:
            raise ConfigError("--models is empty")
        no_fallback = replace(settings.fallback, enabled=False)
        rows = [
            await _evaluate(replace(settings, model=slug, fallback=no_fallback), args, prompt, samples, chunks)
            for slug in resolve_models(settings, names)
        ]
        report = write_comparison(args.output_dir, prompt=prompt, rows=rows)
        print(comparison_table(rows))
        logger.info("comparison saved to %s", report)
        return 0 if all(r["summary"]["failed"] == 0 for r in rows) else 1

    if args.model:
        settings = replace(settings, model=settings.models.get(args.model, args.model))
    row = await _evaluate(settings, args, prompt, samples, chunks)
    logger.info("run finished model=%s summary=%s", row["model"], json.dumps(row["summary"], ensure_ascii=False))
    print(json.dumps(row["summary"], ensure_ascii=False, indent=2))
    print(comparison_table([row]))
    return 0 if row["summary"]["failed"] == 0 else 1

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(console_level=level, file_level=level, log_file=resolve_log_file(args.log_file))
    load_dotenv(ROOT / ".env")
    try:
        return asyncio.run(_run(args))
    except (ConfigError, PromptError, SampleError, KnowledgeError, IntakeError) as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
