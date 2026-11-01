from __future__ import annotations

import logging
import re
from functools import partial
from pathlib import Path

import httpx
import pytest

from hr_compass import chat, logging_setup
from hr_compass.logging_setup import configure_logging, resolve_log_file
from hr_compass.openrouter import OpenRouterClient
from tests.test_chat import ANSWER_OK, INTAKE_OK, FakeLLM, ask, bot, chat_completion

SECRET_QUESTION = "У мене діагноз XYZ-SECRET, скільки лікарняних?"


def test_resolve_log_file_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(logging_setup.LOG_FILE_ENV, raising=False)
    assert resolve_log_file(None) == logging_setup.DEFAULT_LOG_FILE
    monkeypatch.setenv(logging_setup.LOG_FILE_ENV, str(tmp_path / "env.log"))
    assert resolve_log_file(None) == tmp_path / "env.log"
    assert resolve_log_file(tmp_path / "cli.log") == tmp_path / "cli.log"  # CLI beats env
    monkeypatch.setenv(logging_setup.LOG_FILE_ENV, "off")
    assert resolve_log_file(None) is None and resolve_log_file(Path("OFF")) is None


def test_configure_logging_is_idempotent_and_writes_file(tmp_path: Path) -> None:
    log = tmp_path / "x" / "app.log"  # parent directory is created
    configure_logging(log_file=log)
    configure_logging(log_file=log)
    logger = logging.getLogger("hr_compass")
    assert len([h for h in logger.handlers if getattr(h, logging_setup._OWN, False)]) == 2  # console + file, not 4
    logging.getLogger("hr_compass.test").info("hello")
    for h in logger.handlers:
        h.flush()
    assert "hello" in log.read_text(encoding="utf-8")


def test_unwritable_log_file_does_not_break_startup(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="hr_compass"):
        configure_logging(log_file=blocker / "app.log")  # parent is a file -> OSError
    assert "log file disabled" in caplog.text


def test_pipeline_logs_key_steps_with_request_id_and_no_question_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = FakeLLM()
    with caplog.at_level(logging.INFO, logger="hr_compass"):
        ask(bot(llm), SECRET_QUESTION)
    text = caplog.text
    assert "ask start" in text and "ask done kind=answer" in text and "context built" in text
    assert "sources=3-3" in text and "cost=$0.002000" in text
    assert "XYZ-SECRET" not in text  # question text is DEBUG-only
    ids = {r.getMessage().split()[0] for r in caplog.records}  # sanity: records exist
    assert ids


def test_question_text_appears_only_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        ask(bot(FakeLLM()), SECRET_QUESTION)
    assert "XYZ-SECRET" in caplog.text


def test_request_id_is_set_during_ask_and_reset_after() -> None:
    seen: list[str] = []

    class Spy(FakeLLM):
        async def generate(self, messages, **kwargs):
            seen.append(logging_setup.request_id.get())
            return await super().generate(messages, **kwargs)

    ask(bot(Spy()))
    assert len(seen) == 2 and seen[0] == seen[1] != "-"  # intake and answer share one id
    assert logging_setup.request_id.get() == "-"


def test_branch_decisions_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="hr_compass"):
        ask(bot(FakeLLM(intake={**INTAKE_OK, "in_scope": False})))
        ask(bot(FakeLLM(intake={**INTAKE_OK, "needs_clarification": True, "clarifying_question": "?"})))
    assert "out of scope" in caplog.text and "clarifying question" in caplog.text


def test_failures_are_logged_as_errors(caplog: pytest.LogCaptureFixture) -> None:
    from hr_compass.resilient import LLMError

    with caplog.at_level(logging.INFO, logger="hr_compass"), pytest.raises(LLMError):
        ask(bot(FakeLLM(answer=LLMError(["m: down"]))))
    assert any(r.levelno == logging.ERROR and "ask failed" in r.getMessage() for r in caplog.records)


def test_llm_call_is_logged_and_api_key_never_is(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    key = "sk-or-SUPER-SECRET-KEY"
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    monkeypatch.setattr(chat, "load_dotenv", lambda *_: None)

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        system = json.loads(request.content)["messages"][0]["content"]
        payload = INTAKE_OK if "pre-analysis module" in system else ANSWER_OK
        return httpx.Response(200, json=chat_completion(json.dumps(payload)))

    monkeypatch.setattr(chat, "OpenRouterClient", partial(OpenRouterClient, transport=httpx.MockTransport(handler)))
    log = tmp_path / "run.log"
    with caplog.at_level(logging.DEBUG, logger="hr_compass"):
        assert chat.main([SECRET_QUESTION, "--log-file", str(log), "--debug"]) == 0
    for h in logging.getLogger("hr_compass").handlers:
        h.flush()
    file_text = log.read_text(encoding="utf-8")
    for text in (caplog.text, file_text):
        assert "llm call ok model=openai/gpt-4o-mini" in text and "input_tokens=100 output_tokens=10" in text
        assert re.search(r"intake language=.* input_tokens=100 output_tokens=10", text)
        assert re.search(r"ask done .* input_tokens=200 output_tokens=20", text)  # intake + answer
        assert "config loaded" in text and "knowledge loaded chunks=108" in text
        assert key not in text and "Bearer" not in text
    assert "started args" in file_text


def test_fallback_and_retry_failures_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    import asyncio

    from hr_compass.config import FallbackConfig, RetryConfig, Settings, StructuredOutputConfig
    from hr_compass.resilient import ResilientLLM

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        model = json.loads(request.content)["model"]
        if model == "bad/model":
            return httpx.Response(404, json={"error": {"message": "no such model"}})
        return httpx.Response(200, json=chat_completion("plain"))

    settings = Settings(
        api_key="k",
        model="bad/model",
        retry=RetryConfig(max_retries=0),
        structured_output=StructuredOutputConfig(enabled=False),
        fallback=FallbackConfig(enabled=True, models=("good/model",)),
    )

    async def go():
        async with OpenRouterClient(settings, transport=httpx.MockTransport(handler)) as client:
            return await ResilientLLM(client, settings).generate([{"role": "user", "content": "hi"}])

    with caplog.at_level(logging.INFO, logger="hr_compass"):
        result = asyncio.run(go())
    assert result.model_used == "good/model"
    assert "llm call rejected model=bad/model status=404" in caplog.text
    assert "fallback used: answered by good/model" in caplog.text


TIMING = re.compile(r"attempt_time=\d+\.\d\ds total=\d+\.\d\ds")


def _call_with(responses: list[httpx.Response], *, max_retries: int):
    import asyncio

    from hr_compass.config import RetryConfig, Settings

    queue = list(responses)
    settings = Settings(api_key="k", model="m/x", retry=RetryConfig(max_retries=max_retries, base_delay_s=0.0))

    async def go():
        async with OpenRouterClient(settings, transport=httpx.MockTransport(lambda _: queue.pop(0))) as client:
            return await client.complete([{"role": "user", "content": "hi"}], model="m/x")

    return asyncio.run(go())


def _records(caplog: pytest.LogCaptureFixture, prefix: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith(prefix)]


def test_successful_call_logs_attempt_and_total_time(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="hr_compass"):
        _call_with([httpx.Response(200, json=chat_completion("plain"))], max_retries=0)
    [ok] = _records(caplog, "llm call ok")
    assert ok.levelno == logging.INFO and "attempt=1/1" in ok.getMessage()
    assert TIMING.search(ok.getMessage())


def test_failed_attempt_then_success_logs_timing_for_both(caplog: pytest.LogCaptureFixture) -> None:
    responses = [httpx.Response(503, json={"error": {"message": "busy"}}), httpx.Response(200, json=chat_completion("x"))]
    with caplog.at_level(logging.INFO, logger="hr_compass"):
        _call_with(responses, max_retries=1)
    [failed] = _records(caplog, "llm attempt failed")
    [ok] = _records(caplog, "llm call ok")
    assert failed.levelno == logging.WARNING and "attempt=1/2 status=503" in failed.getMessage()
    assert "attempt=2/2" in ok.getMessage()
    assert TIMING.search(failed.getMessage()) and TIMING.search(ok.getMessage())


def test_exhausted_retries_log_total_time(caplog: pytest.LogCaptureFixture) -> None:
    from hr_compass.openrouter import OpenRouterError

    busy = [httpx.Response(503, json={"error": {"message": "busy"}}) for _ in range(2)]
    with caplog.at_level(logging.INFO, logger="hr_compass"), pytest.raises(OpenRouterError):
        _call_with(busy, max_retries=1)
    assert len(_records(caplog, "llm attempt failed")) == 2
    [gave_up] = _records(caplog, "llm call failed")
    assert gave_up.levelno == logging.ERROR and re.search(r"after 2 attempts total=\d+\.\d\ds", gave_up.getMessage())


def test_rejected_call_logs_timing(caplog: pytest.LogCaptureFixture) -> None:
    from hr_compass.openrouter import OpenRouterError

    with caplog.at_level(logging.INFO, logger="hr_compass"), pytest.raises(OpenRouterError):
        _call_with([httpx.Response(401, json={"error": {"message": "bad key"}})], max_retries=3)
    [rejected] = _records(caplog, "llm call rejected")
    assert rejected.levelno == logging.ERROR and "attempt=1/4" in rejected.getMessage()
    assert TIMING.search(rejected.getMessage())
