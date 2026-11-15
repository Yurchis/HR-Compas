"""Answer evals: deterministic scores first (free, never disagree with themselves), then run metrics, stability
over repeated runs, the judge's agreement with people, and the gate that compares a run with a baseline.

A bot result (`assistant.Reply.as_result()`):

    {"found": True, "answer": "One day a week ...", "cited": ["…/Handbook (US) 2026.docx#105"]}

`found` is False when the bot abstained; `cited` are the chunk_ids the answer relies on. Cases come from
`testset.resolve_cases` (relevant = chunk_ids).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hr_compass.evaluation.domain.testset import norm

TOLERANCE = 0.05                                 # the gate allows a metric to drop this much
LOWER_IS_BETTER = frozenset({"false_abstain", "leaks"})   # for these metrics a rise is the regression


def score(result: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, bool | None]:
    """Deterministic scores for one answer.

    - facts: answerable cases only; the bot found an answer and every `must` group has one option in it
      (after `norm`, so "−15 °C" matches "-15 °c");
    - cited: answerable cases only; a relevant chunk is among the cited ones (the right fact from the wrong
      source is luck, not grounding);
    - abstain: no_answer cases only; the bot said it did not find the answer;
    - pass: facts and cited for answerable cases, abstain for no_answer ones;
    - attributed: found answers only; every statement names its source inline (reported, not part of pass).
    Scores that do not apply are None."""
    relevant = case.get("relevant") or []
    if any(not isinstance(r, str) for r in relevant):
        raise ValueError(f"{case.get('id')}: `relevant` holds quotes; score resolve_cases(...) output")
    if case["kind"] == "no_answer":
        abstain = not result["found"]
        return {"facts": None, "cited": None, "abstain": abstain, "pass": abstain, "attributed": None}
    answer = norm(result.get("answer") or "")
    facts = bool(result["found"]) and all(any(norm(option) in answer for option in group) for group in case["must"])
    cited = bool(set(result.get("cited") or []) & set(relevant))
    attributed = result.get("attributed") if result["found"] else None
    return {"facts": facts, "cited": cited, "abstain": None, "pass": facts and cited, "attributed": attributed}


def rate(values: list) -> float | None:
    """Share of True among the values that apply (None is skipped); None when nothing applies."""
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def aggregate(scores: list[dict], cases: list[Mapping[str, Any]], results: list[Mapping[str, Any]]) -> dict:
    """Metrics over one run: pass, facts, cited, abstain, false_abstain (answerable cases the bot gave up on),
    judge / grounded when present, pass rate by kind and the ids of the failed cases."""
    answerable = [r for r, c in zip(results, cases, strict=True) if c["kind"] != "no_answer"]
    m: dict[str, Any] = {"pass": rate([s["pass"] for s in scores]), "facts": rate([s["facts"] for s in scores]),
                         "cited": rate([s["cited"] for s in scores]), "abstain": rate([s["abstain"] for s in scores]),
                         "false_abstain": rate([not r["found"] for r in answerable]),
                         "attributed": rate([s.get("attributed") for s in scores])}
    for key in ("judge", "grounded"):
        if any(key in s for s in scores):
            m[key] = rate([s.get(key) for s in scores])
    kinds = sorted({c["kind"] for c in cases})
    m["by_kind"] = {k: rate([s["pass"] for s, c in zip(scores, cases, strict=True) if c["kind"] == k]) for k in kinds}
    m["failed"] = [c["id"] for s, c in zip(scores, cases, strict=True) if not s["pass"]]
    return m


def stability(runs: list[list[dict]], cases: list[Mapping[str, Any]]) -> dict:
    """The same testset run several times; runs[i][j] = scores of case j in run i.

    An LLM is not a function: even at temperature 0 a case can pass once and fail the next time.
    - rates: {case id: share of runs it passed};
    - pass_at_1: their mean, the average chance that one answer passes;
    - pass_all: share of cases that passed in every run, what a user asking twice experiences;
    - flaky: ids that passed in some runs but not in all, in testset order."""
    if any(len(run) != len(cases) for run in runs):
        raise ValueError(f"every run needs one score per case ({len(cases)}), got {[len(r) for r in runs]}")
    if not runs or not cases:
        return {"pass_at_1": None, "pass_all": None, "flaky": [], "rates": {}}
    rates = {c["id"]: sum(bool(run[j]["pass"]) for run in runs) / len(runs) for j, c in enumerate(cases)}
    return {"pass_at_1": sum(rates.values()) / len(rates),
            "pass_all": sum(r == 1.0 for r in rates.values()) / len(rates),
            "flaky": [cid for cid, r in rates.items() if 0 < r < 1],
            "rates": rates}


def calibrate(judged: list[bool], human: list[bool], ids: list[str]) -> dict:
    """The judge against people: judged[i] and human[i] are True when answer i was marked correct.

    - agreement: share of items where judge == person;
    - false_pass: share of items the judge passed but a person failed (inflates every number built on it);
    - false_fail: share of items the judge failed but a person passed;
    - disagreements: ids of the items where they differ: read every one, half of them may be testset bugs."""
    if not len(judged) == len(human) == len(ids):
        raise ValueError(f"judged, human and ids differ in length: {len(judged)}, {len(human)}, {len(ids)}")
    n = len(ids)
    if not n:
        return {"agreement": None, "false_pass": None, "false_fail": None, "disagreements": []}
    pairs = list(zip(judged, human, strict=True))
    return {"agreement": sum(j == h for j, h in pairs) / n,
            "false_pass": sum(j and not h for j, h in pairs) / n,
            "false_fail": sum(h and not j for j, h in pairs) / n,
            "disagreements": [i for i, (j, h) in zip(ids, pairs, strict=True) if j != h]}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def gate(metrics: Mapping[str, Any], baseline: Mapping[str, Any], tolerance: float = TOLERANCE) -> list[str]:
    """Compare the current metrics with the baseline; an empty list means the gate is green.

    Failures, one line each:
    - every number of the baseline that is now lower by more than `tolerance` (for LOWER_IS_BETTER metrics:
      higher), e.g. "pass: 0.90 -> 0.80 (-0.10)"; a key "<config>/<metric>" counts by its metric name;
    - a baseline number that is not measured now (a run without the judge cannot vouch for `judge`);
    - every case that passed in the baseline and fails now: "regression: q16". With baseline["cases"] (the
      ids it ran), a case added since then is not a regression."""
    failures: list[str] = []
    for key, base in baseline.items():
        if not _number(base):
            continue
        now = metrics.get(key)
        if not _number(now):
            failures.append(f"{key}: {base:.2f} in the baseline, not measured now")
            continue
        lower_is_better = key.rsplit("/", 1)[-1] in LOWER_IS_BETTER
        worse_by = round((now - base) if lower_is_better else (base - now), 9)   # 0.90 - 0.85 is 0.05000000000000004
        if worse_by > tolerance:
            failures.append(f"{key}: {base:.2f} -> {now:.2f} ({now - base:+.2f})")
    known = set(baseline["cases"]) if "cases" in baseline else None
    failed_before = set(baseline.get("failed", []))
    failures += [f"regression: {cid}" for cid in metrics.get("failed", [])
                 if cid not in failed_before and (known is None or cid in known)]
    return failures
