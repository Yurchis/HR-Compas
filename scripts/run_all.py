"""Run the whole evaluation matrix in one go — every prompt × every model — and write results/summary.md.

    python scripts/run_all.py                                   # default matrix: 3 prompts × 3 models
    python scripts/run_all.py --clean                           # first remove previous runs from results/runs/
    python scripts/run_all.py --prompts v3_country_clarification --models deepseek --limit 3   # quick check
    python scripts/run_all.py --rerank                          # the same matrix with the reranker
    python scripts/run_all.py --summary-only                    # only rebuild results/summary.md from results/runs/

Each prompt is one `hr_compass.evaluate --models ...` call (fallback off, intake on), exactly like running the
commands by hand. Works without activating .venv (re-runs itself with .venv's Python, like main.py).
`v1_baseline` is not in the default matrix: it needs `[structured_output].enabled = false` (pass such a --config).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import SETUP_HINT, VENV_PYTHON, _dependencies_missing  # noqa: E402  (stdlib-only module)

DEFAULT_PROMPTS = ("v2_structured", "v3_country_clarification", "v4_country_clarification_en")
DEFAULT_MODELS = ("gpt4omini", "haiku", "deepseek")
RUNS_DIR = ROOT / "results" / "runs"
SUMMARY = ROOT / "results" / "summary.md"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_all.py", description=__doc__.splitlines()[0])
    p.add_argument("--prompts", default=",".join(DEFAULT_PROMPTS),
                   help="comma-separated prompt names from prompts/ (or paths)")
    p.add_argument("--models", default=",".join(DEFAULT_MODELS), help="comma-separated aliases from [models] or slugs")
    p.add_argument("--samples", type=Path, default=ROOT / "data" / "golden_set.jsonl")
    p.add_argument("--config", type=Path, help="settings file (default: config/settings.toml)")
    p.add_argument("--limit", type=int, help="only the first N questions (quick check)")
    p.add_argument("--rerank", action="store_true", help="use the reranker instead of the full context")
    p.add_argument("--clean", action="store_true", help="delete everything in results/runs/ before running")
    p.add_argument("--summary-only", action="store_true", help="do not run anything, rebuild results/summary.md")
    return p


def prompt_path(name: str) -> Path:
    path = Path(name)
    if path.suffix == ".md" and path.is_file():
        return path
    candidate = ROOT / "prompts" / f"{name.removesuffix('.md')}.md"
    if not candidate.is_file():
        raise SystemExit(f"prompt not found: {name} (looked for {candidate})")
    return candidate


def evaluate_argv(args: argparse.Namespace, prompt: Path, models: Sequence[str]) -> list[str]:
    argv = ["--prompt", str(prompt), "--samples", str(args.samples), "--models", ",".join(models)]
    if args.config:
        argv += ["--config", str(args.config)]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    argv.append("--rerank" if args.rerank else "--no-rerank")
    return argv


def run_dirs() -> set[Path]:
    return {p for p in RUNS_DIR.iterdir() if p.is_dir()} if RUNS_DIR.is_dir() else set()


def clean_runs() -> int:
    """Delete every run folder and compare file in results/runs/ (the folder itself stays)."""
    removed = 0
    for item in list(RUNS_DIR.iterdir()) if RUNS_DIR.is_dir() else []:
        shutil.rmtree(item) if item.is_dir() else item.unlink()
        removed += 1
    return removed


def main(argv: Sequence[str] | None = None) -> int:
    from hr_compass import evaluate
    from hr_compass.summary import summary_markdown

    args = build_parser().parse_args(argv)
    if args.summary_only:
        dirs = sorted(run_dirs())
        if not dirs:
            print(f"no runs in {RUNS_DIR}", file=sys.stderr)
            return 1
        SUMMARY.write_text(summary_markdown(dirs), encoding="utf-8")
        print(f"summary of {len(dirs)} run(s) -> {SUMMARY}")
        return 0

    prompts = [prompt_path(p.strip()) for p in args.prompts.split(",") if p.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not prompts or not models:
        print("--prompts and --models must not be empty", file=sys.stderr)
        return 2
    if args.clean:
        print(f"removed {clean_runs()} item(s) from {RUNS_DIR}")

    print(f"matrix: {len(prompts)} prompt(s) × {len(models)} model(s) = {len(prompts) * len(models)} run(s); "
          f"context: {'rerank' if args.rerank else 'full'}; questions: {args.limit or 'all'}")
    before, codes = run_dirs(), []
    for i, prompt in enumerate(prompts, 1):
        print(f"\n=== [{i}/{len(prompts)}] prompt {prompt.stem} on {', '.join(models)}", flush=True)
        codes.append(evaluate.main(evaluate_argv(args, prompt, models)))

    new_runs = sorted(run_dirs() - before)
    if new_runs:
        SUMMARY.write_text(summary_markdown(new_runs), encoding="utf-8")
        print(f"\nsummary of {len(new_runs)} new run(s) -> {SUMMARY}")
    failed = [p.stem for p, c in zip(prompts, codes) if c != 0]
    if failed:
        print(f"some questions failed for prompt(s): {', '.join(failed)} (see the logs / results.jsonl)", file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    if _dependencies_missing():
        if not VENV_PYTHON.is_file() or Path(sys.executable).resolve() == VENV_PYTHON.resolve():
            print(SETUP_HINT, file=sys.stderr)
            sys.exit(2)
        try:
            sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]))
        except KeyboardInterrupt:
            sys.exit(130)
    sys.exit(main())
