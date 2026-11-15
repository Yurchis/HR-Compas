"""The dependency rule of the bounded-context layout, checked on the imports of every module:

- a `domain` package imports only the standard library, pydantic, the shared kernel and other `domain` packages:
  no I/O libraries, no application, infrastructure or CLI code;
- an `application` package never imports infrastructure (it depends on ports) nor the CLI;
- the shared kernel never imports a bounded context;
- only the CLI (the composition root) wires infrastructure into use cases.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hr_compass.shared.paths import ROOT

PACKAGE = ROOT / "hr_compass"
CONTEXTS = ("ingestion", "knowledge", "assistant", "evaluation")
IO_LIBRARIES = {"qdrant_client", "fastembed", "httpx", "rank_bm25", "bs4", "pypdf", "docx", "tiktoken", "numpy",
                "truststore", "dotenv", "openai"}


def modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def layer(path: Path) -> tuple[str, str]:
    """(context or 'shared' / 'cli', layer or '')"""
    parts = path.relative_to(PACKAGE).parts
    return parts[0], parts[1] if len(parts) > 2 else ""


def _violations(path: Path) -> list[str]:
    context, kind = layer(path)
    problems = []
    for name in imports(path):
        top = name.split(".")[0]
        inner = name.split(".")[1:3] if name.startswith("hr_compass.") else []
        if kind == "domain":
            if top in IO_LIBRARIES:
                problems.append(f"domain imports the I/O library {name}")
            if (inner[:1] == ["cli"]) or (len(inner) == 2 and inner[1] in ("application", "infrastructure")):
                problems.append(f"domain imports {name}")
        if kind == "application" and (inner[:1] == ["cli"] or (len(inner) == 2 and inner[1] == "infrastructure")):
            problems.append(f"application imports {name}")
        if context == "shared" and inner and inner[0] in (*CONTEXTS, "cli"):
            problems.append(f"the shared kernel imports {name}")
    return problems


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_the_dependency_rule(path: Path):
    assert _violations(path) == []


@pytest.mark.parametrize(("module", "bad_import"), [
    ("knowledge/domain/chunk.py", "qdrant_client"),
    ("knowledge/domain/chunk.py", "hr_compass.knowledge.infrastructure.files"),
    ("ingestion/domain/document.py", "hr_compass.ingestion.application.ingest_documents"),
    ("assistant/application/ask_question.py", "hr_compass.assistant.infrastructure.resilient_llm"),
    ("evaluation/application/eval_answers.py", "hr_compass.cli.container"),
    ("shared/settings.py", "hr_compass.knowledge.domain.chunk"),
])
def test_the_checker_catches_a_violation(monkeypatch, module, bad_import):
    """The rule above is only worth something if it fails on a bad import."""
    monkeypatch.setattr(__import__(__name__, fromlist=["imports"]), "imports", lambda path: {bad_import})

    assert _violations(PACKAGE / module)


def test_every_context_has_the_three_layers():
    for context in CONTEXTS:
        assert {p.name for p in (PACKAGE / context).iterdir() if p.is_dir() and p.name != "__pycache__"} >= {
            "domain", "application", "infrastructure"}, context


def test_no_module_keeps_mutable_state_in_globals():
    """Models, caches and clients live in objects built by the composition root, not in module variables."""
    for path in modules():
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Global) or (isinstance(node, ast.FunctionDef) and any(
                    isinstance(n, ast.Global) for n in ast.walk(node))):
                pytest.fail(f"{path.relative_to(PACKAGE)} uses `global`")
