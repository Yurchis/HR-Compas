"""Project paths, defined once. Relative paths in settings are relative to ROOT, not to the working directory."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"


def resolve(path: str | Path) -> Path:
    """An absolute path as is; a relative one against the project root."""
    path = Path(path)
    return path if path.is_absolute() else ROOT / path
