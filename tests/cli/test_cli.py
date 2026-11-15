"""`hr-compass` end to end through main(): ingest, lint, chat (HTTP mocked), errors, and main.py."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import httpx
import pytest

import main as entry
from hr_compass.cli import chat_command
from hr_compass.cli.container import Container
from hr_compass.cli.main import build_parser
from hr_compass.cli.main import main as cli
from hr_compass.knowledge.application.search_service import SearchService
from hr_compass.knowledge.domain.access import AccessPolicy
from hr_compass.shared.openrouter import OpenRouterClient
from tests.fakes import DIM, KeywordEmbedder, ListRetriever, OverlapReranker, chunk

PAGE = "<html><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A settings file pointing at a tiny corpus, testset and results folder in tmp_path."""
    src = tmp_path / "docs" / "Usa"
    src.mkdir(parents=True)
    (src / "remote.html").write_text(PAGE.format(title="Remote Work", body="Employees work remotely one day per week."),
                                     encoding="utf-8")
    (tmp_path / "access.json").write_text(json.dumps({"": ["all_employees"]}), encoding="utf-8")
    cases = [{"id": f"q{i}", "kind": "paraphrase", "groups": ["all_employees"], "question": "Remote days?",
              "relevant": [{"quote": "one day per week"}], "must": [["one day"]], "reference": "One day a week."}
             for i in (1, 2)]
    (tmp_path / "testset.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
    config = tmp_path / "settings.toml"
    config.write_text(f'''
[ingest]
source_dir = "{(tmp_path / 'docs').as_posix()}"
output_dir = "{(tmp_path / 'clean').as_posix()}"
[access]
rules_file = "{(tmp_path / 'access.json').as_posix()}"
[eval]
testset = "{(tmp_path / 'testset.json').as_posix()}"
results_dir = "{(tmp_path / 'results').as_posix()}"
[logging]
dir = "{(tmp_path / 'logs').as_posix()}"
''', encoding="utf-8")
    return config


def run(config: Path, *args: str) -> int:
    return cli(["--config", str(config), *args])


def test_ingest_then_lint(project, capsys):
    assert run(project, "--log-file", "off", "ingest") == 0
    out = capsys.readouterr().out
    assert "1 files {'ok': 1}" in out and "chunks 1" in out

    assert run(project, "--log-file", "off", "eval", "lint") == 0
    assert "testset OK" in capsys.readouterr().out


def test_eval_chunks_prints_and_saves_how_the_corpus_is_cut(project, capsys):
    run(project, "--log-file", "off", "ingest")
    capsys.readouterr()

    assert run(project, "--log-file", "off", "eval", "chunks") == 0

    out = capsys.readouterr().out
    assert "strategy headings, limit 120 tokens" in out and "over_limit" in out
    saved = json.loads((project.parent / "results" / "chunk_stats.json").read_text(encoding="utf-8"))
    assert saved["strategy"] == "headings" and saved["chunks"] == 1 and saved["starts_mid_sentence"] == 0


def test_ingest_without_documents_stops_and_keeps_the_prepared_chunks(project, capsys):
    run(project, "--log-file", "off", "ingest")
    chunks = project.parent / "clean" / "chunks.jsonl"
    before = chunks.read_text(encoding="utf-8")
    for doc in (project.parent / "docs").rglob("*.html"):
        doc.unlink()
    capsys.readouterr()

    assert run(project, "--log-file", "off", "ingest") == 1
    assert run(project, "--log-file", "off", "run", "--no-chat") == 1

    out = capsys.readouterr().out
    assert "no documents in" in out and "stopped: nothing to ingest" in out
    assert chunks.read_text(encoding="utf-8") == before   # nothing wiped


def test_lint_fails_on_a_broken_testset(project, capsys):
    run(project, "--log-file", "off", "ingest")
    testset = project.parent / "testset.json"
    data = json.loads(testset.read_text(encoding="utf-8"))
    data["cases"][0]["relevant"] = [{"quote": "two days"}]
    testset.write_text(json.dumps(data), encoding="utf-8")

    assert run(project, "--log-file", "off", "eval", "lint") == 1
    assert "q1: quote 'two days' matches no chunk" in capsys.readouterr().out


def test_commands_without_data_or_key_fail_cleanly(project, capsys, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)

    assert run(project, "--log-file", "off", "eval", "lint") == 2   # no chunks yet
    assert "make pipeline" in capsys.readouterr().err
    assert run(project, "--log-file", "off", "chat", "hi") == 2      # no key
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_the_chat_on_an_empty_index_says_how_to_build_it(project, capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)
    monkeypatch.setattr(Container, "chunks", property(lambda self: []))

    assert run(project, "--log-file", "off", "chat", "hi") == 2
    assert "no documents are indexed" in capsys.readouterr().err


def _completion(payload: dict) -> dict:
    return {"model": "openai/gpt-4o-mini", "choices": [{"message": {"content": json.dumps(payload)},
                                                        "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0001}}


def test_chat_answers_with_sources_and_logs_json_without_the_key(project, capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SUPER-SECRET")
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)
    record = chunk("Usa/remote.html#0", "Employees work remotely one day per week.", section="Remote Work",
                   title="Remote Work", country="USA")
    service = SearchService(ListRetriever([record]), AccessPolicy({}), k=5, mode="test")
    monkeypatch.setattr(Container, "search", property(lambda self: service))
    monkeypatch.setattr(Container, "chunks", property(lambda self: [record]))
    monkeypatch.setattr(Container, "chunks_by_id", property(lambda self: {record.chunk_id: record}))

    def handler(request: httpx.Request) -> httpx.Response:
        schema = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if schema == "intake":
            return httpx.Response(200, json=_completion({"language": "en", "in_scope": True, "country": None,
                                                         "needs_clarification": False, "clarifying_question": None}))
        return httpx.Response(200, json=_completion({"found": True, "answer": "One day a week.", "citations": ["S1"],
                                                     "confidence": "high", "needs_clarification": False}))

    monkeypatch.setattr(chat_command, "OpenRouterClient",
                        partial(OpenRouterClient, transport=httpx.MockTransport(handler)))
    log = project.parent / "chat.log"

    assert run(project, "--log-file", str(log), "chat", "How many days can I work from home?") == 0

    out = capsys.readouterr().out
    assert out.startswith("One day a week.") and "[1] Remote Work — Remote Work" in out
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    done = next(line for line in lines if line["msg"] == "ask done")
    assert done["component"] == "chat" and done["found"] is True and done["input_tokens"] == 200
    assert "SUPER-SECRET" not in log.read_text(encoding="utf-8") and "work from home" not in log.read_text("utf-8")


def test_the_container_picks_the_embedding_provider_from_the_settings(project):
    from hr_compass.knowledge.infrastructure.embedding import FastEmbedModel, OpenRouterEmbeddingModel
    from hr_compass.shared.settings import Settings

    local = Container(Settings.load(project, env={})).embedder
    project.write_text(project.read_text(encoding="utf-8") + '[embeddings]\nprovider = "openrouter"\n'
                       'model = "openai/text-embedding-3-large"\ndim = 3072\n', encoding="utf-8")
    remote = Container(Settings.load(project, env={"OPENROUTER_API_KEY": "k"})).embedder

    assert isinstance(local._model, FastEmbedModel) and isinstance(remote._model, OpenRouterEmbeddingModel)
    assert remote._cache.path.name == "openai-text-embedding-3-large.json"


def test_every_command_is_registered():
    parser = build_parser()
    for argv in (["run"], ["run", "q", "--check", "--no-chat", "--full"], ["ingest"], ["index"], ["search", "q"],
                 ["chat"], ["eval", "lint"], ["eval", "retrieval", "--gate"],
                 ["eval", "pairs"], ["eval", "answers", "--judge"], ["eval", "calibrate"]):
        assert callable(parser.parse_args(argv).func), argv


@pytest.mark.parametrize(("argv", "expected"), [
    ([], ["chat"]),
    (["How", "many", "days?"], ["chat", "How", "many", "days?"]),
    (["--debug", "--groups", "hr"], ["chat", "--debug", "--groups", "hr"]),
    (["run", "--check"], ["run", "--check"]),
    (["ingest", "--full"], ["ingest", "--full"]),
    (["eval", "lint"], ["eval", "lint"]),
])
def test_main_py_starts_the_chat_unless_a_command_is_named(argv, expected):
    assert entry.cli_args(argv) == expected


# ---------------------------------------------------------------- hr-compass run


@pytest.fixture
def offline_models(monkeypatch):
    """The real embedder and reranker would download ~300 MB: use the fakes."""
    monkeypatch.setattr(Container, "embedder", property(lambda self: KeywordEmbedder()))
    monkeypatch.setattr(Container, "reranker", property(lambda self: OverlapReranker()))


def _with_dim(config: Path) -> Path:
    config.write_text(config.read_text(encoding="utf-8") + f"[embeddings]\ndim = {DIM}\n", encoding="utf-8")
    return config


def test_run_prepares_the_data_without_a_key_when_there_is_no_chat(project, offline_models, capsys, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)

    assert run(_with_dim(project), "--log-file", "off", "run", "--no-chat", "--check") == 0

    out = capsys.readouterr().out
    for step in ("[1/3] ingest", "chunks 1", "[2/3] index", "access filter: OK", "testset OK",
                 "gate skipped", "ready:"):
        assert step in out
    assert "[3/3] chat" not in out


def test_run_without_a_key_stops_before_doing_any_work(project, capsys, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)

    assert run(project, "--log-file", "off", "run", "a question") == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert not (project.parent / "clean").exists()   # nothing ingested


def test_run_goes_from_documents_to_an_answer(project, offline_models, capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)
    monkeypatch.setattr(chat_command, "OpenRouterClient", partial(OpenRouterClient, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=_completion(
            {"language": "en", "in_scope": True, "country": None, "needs_clarification": False,
             "clarifying_question": None}
            if json.loads(request.content)["response_format"]["json_schema"]["name"] == "intake" else
            {"found": True, "answer": "One day a week.", "citations": ["S1"], "confidence": "high",
             "needs_clarification": False})))))

    assert run(_with_dim(project), "--log-file", "off", "run", "How many remote days?") == 0

    out = capsys.readouterr().out
    assert out.index("[1/3] ingest") < out.index("[2/3] index") < out.index("[3/3] chat")
    assert "One day a week." in out and "[1] Remote Work" in out   # cited the ingested document


def test_run_stops_when_the_testset_check_fails(project, offline_models, capsys, monkeypatch):
    monkeypatch.setattr("hr_compass.cli.main.load_dotenv", lambda *_: None)
    testset = project.parent / "testset.json"
    data = json.loads(testset.read_text(encoding="utf-8"))
    data["cases"][0]["relevant"] = [{"quote": "two days"}]
    testset.write_text(json.dumps(data), encoding="utf-8")

    assert run(_with_dim(project), "--log-file", "off", "run", "--no-chat", "--check") == 1
    assert "stopped: a check failed" in capsys.readouterr().out


def test_main_py_without_venv_prints_the_setup_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(entry, "VENV_PYTHON", tmp_path / "no-such-python")
    assert entry._run_in_venv() == 2 and "pip install -r requirements.txt" in capsys.readouterr().err


def test_main_py_reruns_itself_with_the_venv_python(monkeypatch, tmp_path):
    fake = tmp_path / "python.exe"
    fake.write_text("", encoding="utf-8")
    seen: list[list[str]] = []
    monkeypatch.setattr(entry, "VENV_PYTHON", fake)
    monkeypatch.setattr(entry.sys, "argv", ["main.py", "How many vacation days?", "--debug"])
    monkeypatch.setattr(entry.subprocess, "call", lambda cmd: seen.append(cmd) or 0)

    assert entry._run_in_venv() == 0
    assert seen == [[str(fake), str(entry.ROOT / "main.py"), "How many vacation days?", "--debug"]]
