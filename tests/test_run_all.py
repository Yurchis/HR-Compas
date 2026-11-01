"""scripts/run_all.py (the whole evaluation matrix) and hr_compass/summary.py (the consolidated table)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from hr_compass.summary import run_row, same_language, summary_markdown

ROOT = Path(__file__).resolve().parent.parent


def load_run_all():
    spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts" / "run_all.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def result(sid: str, *, kw: bool | None = True, kind: bool | None = True, q: str = "q", a: str = "a") -> dict:
    return {"id": sid, "question": q, "answer": a, "keywords_passed": kw, "kind_passed": kind, "error": None}


def write_run(base: Path, name: str, results: list[dict], **meta: object) -> Path:
    run = base / name
    run.mkdir(parents=True)
    total = len(results)
    summary = {
        "total": total, "succeeded": total, "keyword_passed": sum(bool(r["keywords_passed"]) for r in results),
        "keyword_checked": sum(r["keywords_passed"] is not None for r in results),
        "kind_passed": sum(bool(r["kind_passed"]) for r in results),
        "kind_checked": sum(r["kind_passed"] is not None for r in results),
        "prompt_tokens": 1000, "completion_tokens": 50, "latency_p50_s": 1.0, "latency_p95_s": 2.0, "cost_usd": 0.04,
    }
    defaults = {"model": "m/x", "prompt": "v3", "intake": "intake_v2_en", "rerank": None,
                "generation": {"temperature": 0.0, "top_p": 1.0}}
    (run / "summary.json").write_text(json.dumps({**defaults, **meta, "summary": summary}), encoding="utf-8")
    (run / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")
    return run


# --- summary ---------------------------------------------------------------------------------------


def test_language_heuristic() -> None:
    assert same_language("How many days?", "18 days") and same_language("Скільки днів?", "18 днів")
    assert not same_language("How many days?", "18 днів") and not same_language("Скільки?", "18 days")


def test_run_row_groups_by_country_and_computes_cost_per_1000(tmp_path: Path) -> None:
    run = write_run(tmp_path, "r1", [
        result("q01-usa"), result("q01-ua", kw=False), result("q01-cr"),
        result("q01-any", kw=None, kind=False), result("q02-any", kw=None),
        result("q03-usa", q="How many?", a="Скільки"),  # wrong language
    ], rerank="nvidia/rerank")
    row = run_row(run)
    assert (row["kw_usa"], row["kw_ua"], row["kw_cr"]) == ("100.0% (2/2)", "0.0% (0/1)", "100.0% (1/1)")
    assert row["clarify"] == "50.0% (1/2)" and row["language"] == "83.3% (5/6)"
    assert row["context"] == "rerank (nvidia/rerank)" and row["sampling"] == "t=0.0, top_p=1.0"
    assert row["cost_per_1000"] == pytest.approx(0.04 / 6 * 1000, abs=0.01)


def test_summary_markdown_has_a_row_per_run_and_the_total(tmp_path: Path) -> None:
    dirs = [write_run(tmp_path, "a", [result("q01-usa")], model="m/a"),
            write_run(tmp_path, "b", [result("q01-usa")], model="m/b", prompt="v2")]
    md = summary_markdown(dirs)
    header, separator = md.splitlines()[4:6]
    assert header.startswith("| Model | Prompt | Context |") and separator.count("---") == header.count("|") - 1
    assert "| m/b | v2 | full |" in md and "| m/a | v3 | full |" in md
    assert md.index("| m/b | v2") < md.index("| m/a | v3")  # sorted by prompt
    assert "Total cost of these runs: $0.08" in md


# --- run_all ---------------------------------------------------------------------------------------


@pytest.fixture
def run_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = load_run_all()
    monkeypatch.setattr(module, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(module, "SUMMARY", tmp_path / "summary.md")
    return module


def test_runs_every_prompt_for_all_models_and_writes_the_summary(run_all, monkeypatch, tmp_path: Path) -> None:
    from hr_compass import evaluate

    calls: list[list[str]] = []

    def fake_evaluate(argv: list[str]) -> int:
        calls.append(argv)
        prompt = Path(argv[argv.index("--prompt") + 1]).stem
        write_run(tmp_path / "runs", f"run_{prompt}", [result("q01-usa")], prompt=prompt)
        return 0

    monkeypatch.setattr(evaluate, "main", fake_evaluate)
    old = write_run(tmp_path / "runs", "old_run", [result("q01-usa")])  # an earlier run: not in the new summary
    assert run_all.main(["--prompts", "v2_structured,v3_country_clarification", "--models", "haiku,deepseek",
                         "--limit", "3"]) == 0

    assert len(calls) == 2 and all("--models" in c and c[c.index("--models") + 1] == "haiku,deepseek" for c in calls)
    assert calls[0][calls[0].index("--limit") + 1] == "3" and "--no-rerank" in calls[0]
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "v2_structured" in summary and "v3_country_clarification" in summary and old.name not in summary


def test_failed_prompt_gives_exit_code_1(run_all, monkeypatch) -> None:
    from hr_compass import evaluate

    monkeypatch.setattr(evaluate, "main", lambda argv: 1)
    assert run_all.main(["--prompts", "v2_structured", "--models", "deepseek"]) == 1


def test_clean_removes_previous_runs(run_all, monkeypatch, tmp_path: Path) -> None:
    from hr_compass import evaluate

    write_run(tmp_path / "runs", "old", [result("q01-usa")])
    (tmp_path / "runs" / "old_compare.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(evaluate, "main", lambda argv: 0)
    run_all.main(["--prompts", "v2_structured", "--models", "deepseek", "--clean", "--rerank"])
    assert list((tmp_path / "runs").iterdir()) == []


def test_summary_only_and_unknown_prompt(run_all, tmp_path: Path) -> None:
    assert run_all.main(["--summary-only"]) == 1  # nothing to summarize yet
    write_run(tmp_path / "runs", "r", [result("q01-usa")])
    assert run_all.main(["--summary-only"]) == 0 and (tmp_path / "summary.md").is_file()
    with pytest.raises(SystemExit, match="prompt not found"):
        run_all.main(["--prompts", "v9_nope"])
