"""Consolidated English summary of evaluation runs (results/runs/<run>/summary.json + results.jsonl)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_CYRILLIC = re.compile("[а-яіїєґА-ЯІЇЄҐ]")
# Golden-set id suffixes: the same question for each country profile, and without a profile.
COUNTRY_GROUPS = {"usa": "USA", "ua": "UA", "cr": "Costa Rica"}
NO_PROFILE_GROUP = "any"

HEADER = (
    "| Model | Prompt | Context | Sampling | Correct (keywords) | Reply type | USA | UA | Costa Rica "
    "| No country → clarification | Language = question | Input tokens | Output tokens | p50, s | p95, s "
    "| Succeeded | Run cost, $ | Cost per 1000 questions, $ |"
)


def _pct(passed: int, total: int) -> str:
    return f"{round(100 * passed / total, 1)}% ({passed}/{total})" if total else "—"


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def same_language(question: str, answer: str | None) -> bool:
    """Heuristic: Cyrillic in the answer <=> Cyrillic in the question (the golden set is English + Ukrainian)."""
    return bool(_CYRILLIC.search(question)) == bool(_CYRILLIC.search(answer or ""))


def _group(sample_id: str) -> str | None:
    suffix = sample_id.rsplit("-", 1)[-1] if "-" in sample_id else ""
    return suffix if suffix in COUNTRY_GROUPS or suffix == NO_PROFILE_GROUP else None


def run_row(run_dir: Path) -> dict[str, Any]:
    """One table row for a run directory written by `hr_compass.evaluate`."""
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    s = meta["summary"]
    results = [json.loads(line) for line in (run_dir / "results.jsonl").open(encoding="utf-8") if line.strip()]
    by_group: dict[str, list[dict]] = {}
    for r in results:
        if (g := _group(r["id"])) is not None:
            by_group.setdefault(g, []).append(r)
    ok = [r for r in results if not r["error"]]
    gen = meta.get("generation") or {}

    def keywords(group: str) -> str:
        rows = by_group.get(group, [])
        return _pct(sum(bool(r["keywords_passed"]) for r in rows), len(rows))

    no_profile = by_group.get(NO_PROFILE_GROUP, [])
    total = s["total"]
    return {
        "model": meta["model"],
        "prompt": meta["prompt"],
        "context": f"rerank ({meta['rerank']})" if meta.get("rerank") else "full",
        "sampling": f"t={gen.get('temperature', '—')}, top_p={gen.get('top_p', '—')}",
        "intake": meta.get("intake"),
        "correct": _pct(s["keyword_passed"], s["keyword_checked"]),
        "kind": _pct(s.get("kind_passed", 0), s.get("kind_checked", 0)),
        **{f"kw_{g}": keywords(g) for g in COUNTRY_GROUPS},
        "clarify": _pct(sum(bool(r["kind_passed"]) for r in no_profile), len(no_profile)),
        "language": _pct(sum(same_language(r["question"], r["answer"]) for r in ok), len(ok)),
        "input_tokens": s["prompt_tokens"],
        "output_tokens": s["completion_tokens"],
        "p50": s["latency_p50_s"],
        "p95": s["latency_p95_s"],
        "succeeded": f"{s['succeeded']}/{total}",
        "cost": s["cost_usd"],
        "cost_per_1000": round(s["cost_usd"] / total * 1000, 2) if total else None,
        "dir": run_dir.name,
    }


def summary_markdown(run_dirs: Iterable[Path], *, title: str = "Evaluation summary") -> str:
    rows = sorted((run_row(d) for d in run_dirs), key=lambda r: (r["prompt"], r["context"], r["sampling"], r["model"]))
    lines = [f"# {title}", ""]
    intakes = sorted({r["intake"] or "off" for r in rows})
    lines += [
        "Golden set: `data/golden_set.jsonl`. Intake: " + ", ".join(f"`{i}`" for i in intakes) + ". "
        "Metric definitions: `REPORT.md`, section 3. \"Language = question\" and the per-country columns are computed "
        "here from `results.jsonl`; \"Cost per 1000 questions\" = run cost / questions × 1000.",
        "",
        HEADER,
        "|" + "---|" * (HEADER.count("|") - 1),
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['prompt']} | {r['context']} | {r['sampling']} | {r['correct']} | {r['kind']} "
            f"| {r['kw_usa']} | {r['kw_ua']} | {r['kw_cr']} | {r['clarify']} | {r['language']} "
            f"| {_thousands(r['input_tokens'])} | {_thousands(r['output_tokens'])} | {r['p50']} | {r['p95']} "
            f"| {r['succeeded']} | {r['cost']} | {r['cost_per_1000'] if r['cost_per_1000'] is not None else '—'} |"
        )
    lines += ["", f"Total cost of these runs: ${round(sum(r['cost'] for r in rows), 4)}", "",
              "Run directories (`results/runs/`):"]
    lines += [f"- {r['model']} / {r['prompt']} / {r['context']} / {r['sampling']} — `{r['dir']}/`" for r in rows]
    return "\n".join(lines) + "\n"
