"""HR Compass — entry point.

Run: python main.py  (or make run); a single question: python main.py "How many vacation days do I get?"

If the current Python has no project dependencies (e.g. the system Python in a fresh shell) but `.venv` exists,
the script re-runs itself with the `.venv` Python, so `python main.py` works without activating the environment.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SETUP_HINT = """Dependencies are not installed. Run once:
  python -m venv .venv
  .venv\\Scripts\\pip install -r requirements.txt      (Linux/macOS: .venv/bin/pip install -r requirements.txt)
  copy .env.example .env                              (then put OPENROUTER_API_KEY into .env)
and then again: python main.py"""


def _dependencies_missing() -> bool:
    try:
        import dotenv, httpx, pydantic  # noqa: F401, E401
    except ImportError:
        return True
    return False


def _run_in_venv() -> int:
    if not VENV_PYTHON.is_file() or Path(sys.executable).resolve() == VENV_PYTHON.resolve():
        print(SETUP_HINT, file=sys.stderr)
        return 2
    try:
        return subprocess.call([str(VENV_PYTHON), str(ROOT / "main.py"), *sys.argv[1:]])
    except KeyboardInterrupt:  # Ctrl+C reaches the child too; it handles it, we just exit quietly
        return 130


if __name__ == "__main__":
    if _dependencies_missing():
        sys.exit(_run_in_venv())

    from hr_compass.chat import main

    sys.exit(main())
