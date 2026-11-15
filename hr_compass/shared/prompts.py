"""Prompt files: versioned text in prompts/ (see prompts/CHANGELOG.md); published versions are never edited."""

from __future__ import annotations

from pathlib import Path

from hr_compass.shared.paths import PROMPTS_DIR


class PromptError(ValueError):
    """A prompt file is missing or empty."""


def load_prompt(path: Path) -> str:
    if not path.is_file():
        raise PromptError(f"prompt not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise PromptError(f"prompt is empty: {path}")
    return text


def judge_prompt(version: str, name: str) -> str:
    """prompts/<version>/<name>.txt, e.g. judge-v3/correct."""
    return load_prompt(PROMPTS_DIR / version / f"{name}.txt")
