"""`hr-compass eval lint|retrieval|pairs|answers|calibrate`."""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from hr_compass.assistant.infrastructure.resilient_llm import ResilientLLM
from hr_compass.cli.container import Container
from hr_compass.evaluation.application.eval_answers import (
    Outcome,
    answer_cases,
    comparison_table,
    judge_outcomes,
    report_markdown,
    score_outcomes,
    summarize,
)
from hr_compass.evaluation.application.eval_retrieval import RetrievalReport, run_retrieval_eval
from hr_compass.evaluation.application.judges import LlmJudge
from hr_compass.evaluation.application.similar_pairs import similar_pairs
from hr_compass.evaluation.domain.retrieval_metrics import retrieval_questions
from hr_compass.evaluation.domain.scores import calibrate, gate, score, stability
from hr_compass.evaluation.domain.testset import EvalCase, lint, reference_problems, resolve_cases
from hr_compass.evaluation.infrastructure.files import (
    dataset_version,
    load_labels,
    load_testset,
    read_json,
    write_result,
)
from hr_compass.ingestion.domain.chunking import ChunkDraft, chunk_stats
from hr_compass.shared.chat_llm import ChatLLM
from hr_compass.shared.openrouter import OpenRouterClient
from hr_compass.shared.prompts import judge_prompt
from hr_compass.shared.settings import Settings

RETRIEVAL_BASELINE = "retrieval_baseline.json"
ANSWERS_BASELINE = "answers_baseline.json"


def _cases(c: Container) -> list[EvalCase]:
    return load_testset(c.settings.eval.testset)


def _save(c: Container, name: str, payload: dict[str, Any]):
    return write_result(c.settings.eval.results_dir / name, payload,
                        dataset=dataset_version(c.settings.ingest.output_dir), fingerprint=c.settings.fingerprint())


def _gate(c: Container, metrics: dict[str, Any], baseline_name: str) -> bool:
    path = c.settings.eval.results_dir / baseline_name
    if not path.exists():
        raise SystemExit(f"no baseline {path}: run with --save-baseline on the version you trust first")
    failures = gate(metrics, read_json(path), c.settings.eval.tolerance)
    print(f"\nGATE {'FAILED' if failures else 'PASSED'} (tolerance {c.settings.eval.tolerance})")
    for line in failures:
        print(f"  {line}")
    return not failures


# ---------------------------------------------------------------- lint


def lint_command(c: Container, args: argparse.Namespace) -> int:
    cases = _cases(c)
    problems = lint(cases, c.chunks_by_id, kinds_min=c.settings.eval.kinds_min,
                    archive_marker=c.settings.ingest.archive_marker, can_read=c.policy.can_read)
    problems += reference_problems(cases)
    print("\n".join(problems) or "testset OK")
    kinds: dict[str, int] = {}
    for case in cases:
        kinds[case.get("kind", "?")] = kinds.get(case.get("kind", "?"), 0) + 1
    print(f"\n{len(cases)} cases ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}), "
          f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------- retrieval


def _print_retrieval(report: RetrievalReport) -> None:
    print(f"\n{'config':<15}{'recall@' + str(report.k):>10}{'MRR':>8}{'ctx tok':>9}{'ms/query':>10}{'leaks':>7}"
          "   misses")
    for name, r in report.results.items():
        print(f"{name:<15}{r['recall']:>10.2f}{r['mrr']:>8.2f}{r['context_tokens']:>9.0f}{r['ms']:>10.0f}"
              f"{r['leaks']:>7}   {' '.join(r['misses']) or '-'}")
    kinds = list(next(iter(report.results.values()))["recall_by_kind"]) if report.results else []
    print(f"\nrecall@{report.k} by kind: " + "  ".join(kinds))
    for name, r in report.results.items():
        print(f"{name:<15}" + "".join(f"{r['recall_by_kind'][k]:>{len(k) + 2}.2f}" for k in kinds))
    print("\naccess filter: " + ("OK, nothing an ordinary employee may not read, in every configuration"
                                 if report.access_ok else f"LEAK {report.access_leaks}"))
    line = " | ".join(f"{n} {r['recall']:.2f}/{r['mrr']:.2f}" for n, r in report.results.items())
    print(f"\nFOR CHAT: recall@{report.k}/MRR on {len(report.questions)} questions | {line}")


def retrieval_command(c: Container, args: argparse.Namespace) -> int:
    lenient = getattr(args, "lenient", False)
    questions = retrieval_questions(_cases(c), c.chunks_by_id, c.settings.ingest.archive_marker, strict=not lenient)
    if lenient and (cut := [q["id"] for q in questions if not q["relevant"]]):
        print(f"no chunk holds the whole quote of {' '.join(cut)} (cut by the chunking): counted as misses")
    configs = c.search_configurations
    if args.only:
        wanted = [name.strip() for name in args.only.split(",")]
        if unknown := set(wanted) - set(configs):
            raise SystemExit(f"unknown configuration(s) {sorted(unknown)}; choose from {list(configs)}")
        configs = {name: configs[name] for name in wanted}
    print(f"chunks {len(c.chunks)} | questions {len(questions)} | k={c.settings.search.k}")
    report = run_retrieval_eval(configs, questions, c.policy, c.settings.search.k)
    _print_retrieval(report)
    path = _save(c, "retrieval_eval.json", {"k": report.k, "questions": len(questions), "results": report.results,
                                            "access_check": report.access_leaks})
    print(f"saved to {path}")
    metrics = report.gate_metrics()
    if args.save_baseline:
        print(f"baseline saved: {_save(c, RETRIEVAL_BASELINE, metrics)}")
    ok = report.access_ok
    if args.gate:
        ok = _gate(c, metrics, RETRIEVAL_BASELINE) and ok
    return 0 if ok else 1


def chunks_command(c: Container, args: argparse.Namespace) -> int:
    """How the current chunking cuts the corpus (no model calls)."""
    cfg = c.settings.ingest
    drafts = [ChunkDraft(ch.text, tuple(ch.section.split(" > ")) if ch.section else ()) for ch in c.chunks]
    stats = chunk_stats(drafts, c.chunk_tokenizer, limit=cfg.chunk_tokens)
    overlap = f", overlap {cfg.fixed_overlap}" if cfg.strategy == "fixed" else ""
    print(f"strategy {cfg.strategy}, limit {cfg.chunk_tokens} tokens{overlap}")
    for key, value in stats.items():
        print(f"  {key:<20} {value}")
    path = _save(c, "chunk_stats.json", {"strategy": cfg.strategy, "chunk_tokens": cfg.chunk_tokens, **stats})
    print(f"saved to {path}")
    return 0


def pairs_command(c: Container, args: argparse.Namespace) -> int:
    marker = c.settings.ingest.archive_marker
    pool = [ch for ch in c.chunks if marker not in ch.source] if args.skip_archived else c.chunks
    for score_, a, b in similar_pairs(pool, c.embedder, top=args.top):
        print(f"  {score_:.3f}  {a}\n         ~ {b}")
    return 0


# ---------------------------------------------------------------- answers


def _model_settings(settings: Settings, name: str, comparing: bool) -> Settings:
    """One model, without fallback when models are compared (a fallback answer would be another model's)."""
    settings = replace(settings, model=settings.resolve_model(name))
    return replace(settings, fallback=replace(settings.fallback, enabled=False)) if comparing else settings


async def _bot_runs(c: Container, models: list[str], cases: list[EvalCase], repeat: int,
                    intake: bool) -> dict[str, list[list[Outcome]]]:
    runs: dict[str, list[list[Outcome]]] = {}
    for name in models:
        settings = _model_settings(c.settings, name, comparing=len(models) > 1)
        async with OpenRouterClient(settings) as client:
            bot = c.ask_question(ResilientLLM(client, settings), intake=intake)
            runs[settings.model] = []
            for i in range(repeat):
                outcomes = await answer_cases(bot, cases, settings.concurrency)
                runs[settings.model].append(outcomes)
                passed = sum(score(o.result(), case)["pass"] for o, case in zip(outcomes, cases, strict=True))
                print(f"{settings.model} run {i + 1}/{repeat}: pass {passed}/{len(cases)}")
    return runs


def answers_command(c: Container, args: argparse.Namespace) -> int:
    c.settings.require_api_key()
    cases = resolve_cases(_cases(c), c.chunks_by_id, c.settings.ingest.archive_marker)[: args.limit]
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else [c.settings.model]
    runs = asyncio.run(_bot_runs(c, models, cases, args.repeat, intake=not args.no_intake))
    judge = None
    if args.judge:   # synchronous: after the bot's event loop has finished
        version = c.settings.eval.judge_prompts
        judge_llm = ChatLLM(c.settings)
        judge = LlmJudge(judge_llm, judge_prompt(version, "correct"), judge_prompt(version, "grounded"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows: dict[str, dict[str, Any]] = {}
    for model, model_runs in runs.items():
        outcomes, scores = model_runs[0], score_outcomes(cases, model_runs[0])
        if judge:
            judge_outcomes(judge, cases, outcomes, scores)
        metrics = summarize(cases, outcomes, scores)
        if len(model_runs) > 1:
            st = stability([score_outcomes(cases, run) for run in model_runs], cases)
            metrics.update(pass_at_1=st["pass_at_1"], pass_all=st["pass_all"], flaky=st["flaky"], rates=st["rates"])
        rows[model] = metrics
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model)
        prompt = c.settings.rag.prompt.stem
        report = c.settings.eval.results_dir / "answers" / f"{stamp}_{slug}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(report_markdown(model, prompt, metrics, cases, outcomes, scores), encoding="utf-8")
        _save(c, f"answers/{stamp}_{slug}.json", {"model": model, "prompt": prompt, "cases": len(cases),
                                                  "metrics": metrics, "scores": scores,
                                                  "answers": [{"id": o.case_id, **o.result(), "error": o.error}
                                                              for o in outcomes]})
        print(f"report: {report}")
    if judge:
        print(f"judge cost ${judge_llm.cost():.4f}")
        judge_llm.close()
    table = comparison_table(rows)
    print("\n" + table)
    (c.settings.eval.results_dir / "answers" / f"{stamp}_comparison.md").write_text(table + "\n", encoding="utf-8")
    first = rows[next(iter(rows))]
    baseline = {k: v for k, v in first.items() if k not in ("by_kind", "flaky", "rates", "errors")}
    if args.save_baseline:
        print(f"baseline saved: {_save(c, ANSWERS_BASELINE, {**baseline, 'cases': [x['id'] for x in cases]})}")
    return 0 if not args.gate or _gate(c, baseline, ANSWERS_BASELINE) else 1


# ---------------------------------------------------------------- calibrate


def calibrate_command(c: Container, args: argparse.Namespace) -> int:
    items = load_labels(c.settings.eval.labels)
    cases = {case["id"]: case for case in resolve_cases(_cases(c), c.chunks_by_id, c.settings.ingest.archive_marker)}
    version = c.settings.eval.judge_prompts
    with ChatLLM(c.settings) as llm:
        judge = LlmJudge(llm, judge_prompt(version, "correct"), judge_prompt(version, "grounded"))
        judged = [judge.correct(cases[it["case"]], it["answer"]).verdict == "correct" for it in items]
        print(f"judge cost ${llm.cost():.4f}")
    ids, human = [it["id"] for it in items], [it["correct"] for it in items]
    deterministic = [score(it, cases[it["case"]])["pass"] for it in items]
    print(f"{len(items)} answers labelled by people, judge prompts {version}\n")
    print(f"{'':<16}{'agreement':>10}{'false pass':>12}{'false fail':>12}   disagreements")
    for name, verdicts in (("deterministic", deterministic), ("judge", judged)):
        r = calibrate(verdicts, human, ids)
        print(f"{name:<16}{r['agreement']:>10.2f}{r['false_pass']:>12.2f}{r['false_fail']:>12.2f}   "
              f"{' '.join(r['disagreements']) or '-'}")
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    ev = sub.add_parser("eval", help="lint the testset, measure retrieval and answers, gate a release")
    evs = ev.add_subparsers(dest="eval_command", required=True)

    p = evs.add_parser("lint", help="check the testset against the chunks (no model calls); exit 1 on problems")
    p.set_defaults(func=lint_command)

    p = evs.add_parser("retrieval", help="recall@k / MRR of every search configuration + the access check")
    p.add_argument("--only", help="comma-separated configurations (default: all)")
    p.add_argument("--lenient", action="store_true",
                   help="a quote no chunk holds whole (cut by the chunking) is a miss, not an error")
    p.add_argument("--save-baseline", action="store_true", help="remember this run's metrics as the baseline")
    p.add_argument("--gate", action="store_true", help="exit 1 if a metric fell below the baseline")
    p.set_defaults(func=retrieval_command)

    p = evs.add_parser("chunks", help="how the chunking cuts the corpus: sizes, cut sentences and tables")
    p.set_defaults(func=chunks_command)

    p = evs.add_parser("pairs", help="semantic near-duplicate chunks from different documents")
    p.add_argument("--skip-archived", action="store_true")
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=pairs_command)

    p = evs.add_parser("answers", help="run the bot on the testset and score its answers (calls the model)")
    p.add_argument("--models", help="comma-separated aliases/slugs to compare (fallback off); default: the main model")
    p.add_argument("--limit", type=int, help="only the first N cases")
    p.add_argument("--repeat", type=int, default=1, help="run every case N times: pass@1, passed every run, flaky")
    p.add_argument("--judge", action="store_true", help="add the LLM judge (correctness) and groundedness")
    p.add_argument("--no-intake", action="store_true", help="skip the intake step")
    p.add_argument("--save-baseline", action="store_true")
    p.add_argument("--gate", action="store_true")
    p.set_defaults(func=answers_command)

    p = evs.add_parser("calibrate", help="the judge against answers labelled by people ([eval].labels)")
    p.set_defaults(func=calibrate_command)
    ev.set_defaults(component="eval")
