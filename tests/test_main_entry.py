"""main.py: falls back to the .venv Python when the current one has no dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

import main


def test_without_venv_prints_setup_hint(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(main, "VENV_PYTHON", tmp_path / "no-such-python")
    assert main._run_in_venv() == 2
    assert "pip install -r requirements.txt" in capsys.readouterr().err


def test_with_venv_reruns_itself_with_the_same_arguments(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "python.exe"
    fake.write_text("", encoding="utf-8")
    seen: list[list[str]] = []
    monkeypatch.setattr(main, "VENV_PYTHON", fake)
    monkeypatch.setattr(sys, "argv", ["main.py", "How many vacation days?", "--debug"])
    monkeypatch.setattr(main.subprocess, "call", lambda cmd: seen.append(cmd) or 0)
    assert main._run_in_venv() == 0
    assert seen == [[str(fake), str(main.ROOT / "main.py"), "How many vacation days?", "--debug"]]


def test_inside_the_venv_it_does_not_loop(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "VENV_PYTHON", Path(sys.executable))  # we already are "the venv" Python
    assert main._run_in_venv() == 2  # missing deps inside the venv itself: hint, no endless re-run
    assert "Dependencies are not installed" in capsys.readouterr().err
