"""HR Compass — entry point (one command, as the course asks).

    python main.py                                     documents -> chunks -> index -> the interactive HR bot
    python main.py "How many vacation days do I get?"  the same, then one question
    python main.py --check                             + lint the testset and gate the search quality first
    python main.py chat | ingest | index | search | eval   a single step (hr-compass <command>)

The data steps reuse earlier work (unchanged files, cached vectors), so a re-run starts the chat in seconds.

If the current Python has no project dependencies (e.g. the system Python in a fresh shell) but `.venv` exists,
the script re-runs itself with the `.venv` Python, so `python main.py` works without activating the environment.
"""

import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
COMMANDS = {"run", "ingest", "index", "search", "chat", "eval", "-h", "--help"}
SETUP_HINT = """Dependencies are not installed. Run once:
  python -m venv .venv
  .venv\\Scripts\\pip install -r requirements.txt      (Linux/macOS: .venv/bin/pip install -r requirements.txt)
  copy .env.example .env                              (then put OPENROUTER_API_KEY into .env)
and then again: python main.py"""


def _dependencies_missing() -> bool:
    return any(find_spec(name) is None for name in ("dotenv", "httpx", "pydantic", "qdrant_client"))


def _run_in_venv() -> int:
    if not VENV_PYTHON.is_file() or Path(sys.executable).resolve() == VENV_PYTHON.resolve():
        print(SETUP_HINT, file=sys.stderr)
        return 2
    try:
        return subprocess.call([str(VENV_PYTHON), str(ROOT / "main.py"), *sys.argv[1:]])
    except KeyboardInterrupt:  # Ctrl+C reaches the child too; it handles it, we just exit quietly
        return 130


def cli_args(argv: list[str]) -> list[str]:
    """`main.py [question words] [options]` is `hr-compass run ...`: the whole pipeline, then the chat.
    A command name (`main.py chat`, `main.py ingest` ...) passes through."""
    return argv if argv and argv[0] in COMMANDS else ["run", *argv]


if __name__ == "__main__":
    if _dependencies_missing():
        sys.exit(_run_in_venv())

    from hr_compass.cli.main import main

    sys.exit(main(cli_args(sys.argv[1:])))
