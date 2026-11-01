from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

import httpx
import pytest

from hr_compass import chat, evaluate
from hr_compass.config import ConfigError, Settings
from hr_compass.intake import Intake, IntakeError, load_intake_prompt
from hr_compass.knowledge import Chunk, load_chunks
from hr_compass.openrouter import Completion, OpenRouterClient
from hr_compass.pipeline import HRCompass
from hr_compass.prompts import PromptTemplate
from hr_compass.resilient import LLMError, LLMResult
from hr_compass.schema import HRAnswer

ROOT = Path(__file__).resolve().parent.parent
INTAKE_OK = {
    "language": "uk",
    "in_scope": True,
    "country": None,
    "sub_company": None,
    "needs_clarification": False,
    "clarifying_question": None,
}
ANSWER_OK = {"found": True, "answer": "40 годин.", "sources": ["3-3"], "confidence": "high"}


def completion(text: str = "", cost: float = 0.001) -> Completion:
    return Completion(text=text, model="m", finish_reason="stop", prompt_tokens=100, completion_tokens=10, cost_usd=cost)


class FakeLLM:
    """Stands in for ResilientLLM: returns a scripted Intake / HRAnswer and records the calls."""

    def __init__(self, intake: dict | Exception | None = None, answer: dict | Exception | None = None) -> None:
        self.intake = INTAKE_OK if intake is None else intake
        self.answer = ANSWER_OK if answer is None else answer
        self.calls: list[tuple[type, list[dict[str, str]]]] = []

    async def generate(self, messages, *, output_model=HRAnswer) -> LLMResult:
        self.calls.append((output_model, messages))
        payload = self.intake if output_model is Intake else self.answer
        if isinstance(payload, Exception):
            raise payload
        return LLMResult(completion(), output_model(**payload), "fake/model")


def chunk(cid: str, country: str = "USA") -> Chunk:
    return Chunk(cid, f"T{cid}", "S", country, ("IT-Product",), ("all",), "paid", None, f"text {cid}")


def bot(llm: FakeLLM, *, intake: bool = True) -> HRCompass:
    prompt = PromptTemplate("p", "RULES\n{{context}}")
    return HRCompass(llm, prompt, [chunk("1-1"), chunk("1-2")], intake_prompt="intake" if intake else None)


def ask(b: HRCompass, question: str = "q", **kw):
    return asyncio.run(b.ask(question, **kw))


# --- intake ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["intake_promt.md", "intake_v2_en.md"])
def test_shipped_intake_prompt_is_usable(name: str) -> None:
    text = load_intake_prompt(ROOT / "prompts" / name)
    example = text[text.rindex("{") : text.rindex("}") + 1]  # the JSON example at the end of the prompt
    Intake.model_validate_json(example)


def test_intake_prompt_missing_or_empty(tmp_path: Path) -> None:
    with pytest.raises(IntakeError, match="not found"):
        load_intake_prompt(tmp_path / "nope.md")
    empty = tmp_path / "e.md"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(IntakeError, match="empty"):
        load_intake_prompt(empty)


# --- pipeline ----------------------------------------------------------------------------------


def test_answer_flow_sums_usage_and_returns_sources() -> None:
    llm = FakeLLM()
    reply = ask(bot(llm), "Скільки годин відпустки?")
    assert (reply.kind, reply.text, reply.sources, reply.found) == ("answer", "40 годин.", ("3-3",), True)
    assert [c[0] for c in llm.calls] == [Intake, HRAnswer]
    assert reply.prompt_tokens == 200 and reply.cost_usd == pytest.approx(0.002)
    assert "text 1-1" in llm.calls[1][1][0]["content"]  # handbook is in the answer's system prompt


def test_out_of_scope_skips_the_answer_call_and_uses_question_language() -> None:
    llm = FakeLLM(intake={**INTAKE_OK, "in_scope": False, "language": "ru"})
    reply = ask(bot(llm), "Какая погода?")
    assert reply.kind == "out_of_scope" and "HR" in reply.text
    assert len(llm.calls) == 1
    unknown = FakeLLM(intake={**INTAKE_OK, "in_scope": False, "language": "de"})
    assert "contact HR" in ask(bot(unknown)).text  # unknown language falls back to English


def test_clarification_is_returned_unless_disabled() -> None:
    intake = {**INTAKE_OK, "needs_clarification": True, "clarifying_question": "Full-time чи part-time?"}
    llm = FakeLLM(intake=intake)
    reply = ask(bot(llm))
    assert (reply.kind, reply.text) == ("clarification", "Full-time чи part-time?")
    assert len(llm.calls) == 1
    assert ask(bot(FakeLLM(intake=intake)), allow_clarification=False).kind == "answer"


def test_profile_without_matching_chunks_falls_back_to_full_handbook() -> None:
    llm = FakeLLM(intake={**INTAKE_OK, "country": "UA"})  # handbook has USA chunks only
    reply = ask(bot(llm))
    assert reply.kind == "answer"
    assert "text 1-1" in llm.calls[1][1][0]["content"]


def test_intake_failure_degrades_to_plain_answer() -> None:
    llm = FakeLLM(intake=LLMError(["m: boom"]))
    reply = ask(bot(llm))
    assert reply.kind == "answer" and reply.intake is None


def test_intake_can_be_disabled_and_answer_failure_propagates() -> None:
    llm = FakeLLM()
    assert ask(bot(llm, intake=False)).intake is None and len(llm.calls) == 1
    with pytest.raises(LLMError):
        ask(bot(FakeLLM(answer=LLMError(["m: down"]))))


# --- config / CLI wiring -------------------------------------------------------------------------


def test_shipped_config_has_model_aliases() -> None:
    s = Settings.load(env={"OPENROUTER_API_KEY": "k"})
    assert {"gpt4omini", "haiku", "deepseek", "luna"} <= set(s.models)
    assert s.models["gpt4omini"] == s.model == "openai/gpt-4o-mini"


def test_config_rejects_empty_model_slug(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    f.write_text('[models]\nx = ""\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="slug"):
        Settings.load(f, {"OPENROUTER_API_KEY": "k"})


def chat_completion(text: str) -> dict:
    return {
        "model": "m",
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001},
    }


def install_fake_api(monkeypatch: pytest.MonkeyPatch, module, seen: list[dict]) -> None:
    """Route the module's OpenRouterClient to an in-memory transport that answers intake and answer calls."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        is_intake = "pre-analysis module" in body["messages"][0]["content"]
        return httpx.Response(200, json=chat_completion(json.dumps(INTAKE_OK if is_intake else ANSWER_OK)))

    monkeypatch.setattr(module, "OpenRouterClient", partial(OpenRouterClient, transport=httpx.MockTransport(handler)))


def test_main_one_shot_prints_answer_and_sources(monkeypatch, capsys) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen: list[dict] = []
    install_fake_api(monkeypatch, chat, seen)
    assert chat.main(["Скільки", "годин", "відпустки?", "--model", "haiku", "--debug"]) == 0
    out = capsys.readouterr().out
    assert "40 годин." in out and "Sources: [3-3]" in out and "[intake]" in out
    assert [b["model"] for b in seen] == ["anthropic/claude-haiku-5.5"] * 2  # alias resolved, intake + answer


def test_main_without_api_key_is_a_clean_error(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(chat, "load_dotenv", lambda *_: None)  # do not pick up a real .env
    assert chat.main(["hi"]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_interactive_mode_handles_clarification_then_exit(monkeypatch, capsys) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    asked = {"n": 0}
    intake = {**INTAKE_OK, "needs_clarification": True, "clarifying_question": "Full-time чи part-time?"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "pre-analysis module" in body["messages"][0]["content"]:
            asked["n"] += 1
            return httpx.Response(200, json=chat_completion(json.dumps(intake)))
        assert "Employee's clarification: full-time" in body["messages"][1]["content"]
        return httpx.Response(200, json=chat_completion(json.dumps(ANSWER_OK)))

    monkeypatch.setattr(chat, "OpenRouterClient", partial(OpenRouterClient, transport=httpx.MockTransport(handler)))
    lines = iter(["Скільки відпустки?", "full-time", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    assert chat.main([]) == 0
    out = capsys.readouterr().out
    assert "Full-time чи part-time?" in out and "40 годин." in out
    assert asked["n"] == 2  # second round still runs intake but may not ask again


# --- multi-model evaluation ----------------------------------------------------------------------


def test_resolve_models_maps_aliases_and_dedups() -> None:
    s = Settings.load(env={"OPENROUTER_API_KEY": "k"})
    assert evaluate.resolve_models(s, ["haiku", "vendor/raw-slug", "haiku"]) == [s.models["haiku"], "vendor/raw-slug"]


def test_models_flag_runs_each_model_without_fallback_and_writes_comparison(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion(json.dumps(ANSWER_OK)))

    monkeypatch.setattr(evaluate, "OpenRouterClient", partial(OpenRouterClient, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(evaluate, "load_dotenv", lambda *_: None)
    code = evaluate.main(
        ["--prompt", str(ROOT / "prompts" / "v2_structured.md"), "--models", "haiku,vendor/x", "--limit", "2",
         "--output-dir", str(tmp_path)]
    )
    assert code == 0
    assert {b["model"] for b in seen} == {"anthropic/claude-haiku-5.5", "vendor/x"}  # no fallback model was ever called
    compare = next(tmp_path.glob("*_compare_*.md")).read_text(encoding="utf-8")
    assert "anthropic/claude-haiku-5.5" in compare and "vendor/x" in compare and "2/2" in compare
    assert len(list(tmp_path.glob("*_anthropic-claude-haiku-5.5_v2_structured"))) == 1
    assert "| Model |" in capsys.readouterr().out


def test_models_flag_rejects_empty_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(evaluate, "load_dotenv", lambda *_: None)
    code = evaluate.main(["--prompt", str(ROOT / "prompts" / "v2_structured.md"), "--models", " , ",
                          "--output-dir", str(tmp_path)])
    assert code == 2


def test_real_handbook_still_loads() -> None:
    chunks = load_chunks(ROOT / "data" / "raw")
    assert len(chunks) == 108
    assert sum(c.country == "USA" for c in chunks) == 58
    assert sum(c.country == "UA" for c in chunks) == 25  # Handbook - Ukraine, IT-Product only
    assert all(c.sub_company == ("IT-Product",) for c in chunks if c.country == "UA")
    assert sum(c.country == "Costa Rica" for c in chunks) == 25  # built from the Ukraine handbook, IT-Outsourcing only
    assert all(c.sub_company == ("IT-Outsourcing",) for c in chunks if c.country == "Costa Rica")
