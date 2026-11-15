# evals/

Everything the project measures with: the testset, the scoring functions, and the results of every run. Numbers and
conclusions are in [`REPORT.md`](../REPORT.md); how to run the evals is in the main [`README.md`](../README.md),
section "Evaluation".

## Testset and labels

| File | What |
|---|---|
| [`testset.json`](testset.json) | the golden set, 26 cases (details below) |
| [`labels.json`](labels.json) | 30 real bot answers labelled correct / incorrect by a person, blind to the judge, to calibrate the LLM judge (`eval calibrate`) |
| [`testset_review.md`](testset_review.md) | a sheet for a person to check every case against the text of its source chunk (`Verdict: OK / FIX`) |

**Kinds of cases in `testset.json`:**
- paraphrase 11;
- exact term 4;
- cross-lingual 4: a Ukrainian question about an English document;
- access 2: a hr-only document;
- stale 2: an archived handbook says otherwise;
- no_answer 3: the documents do not answer, and the bot must say so.

**Fields of a case:**
- `question` and `groups` (who asks);
- `relevant`: the source as a quote, resolved to chunk ids at load time, so the labels survive re-chunking;
- `must`: the key facts;
- `reference`: the expected answer, which the judge reads;
- `trap` (optional): what an outdated or similar source would say. The judge does not read it.

The format and the lint rules are in `hr_compass/evaluation/domain/testset.py`.

## Scoring functions

The code lives in the package, because the CLI and the tests import it. This is the map:

| Score | What it checks | Kind | Where |
|---|---|---|---|
| `recall@k`, `MRR` | a relevant chunk is in the top k; 1 / rank of the first one | deterministic, retrieval | `hr_compass/evaluation/domain/retrieval_metrics.py` → `evaluate()` |
| leaks, access check | no search returns a chunk the user may not read | deterministic, retrieval | `retrieval_metrics.py` → `evaluate()`, `check_access()` |
| `cited` | a relevant chunk is among the answer's sources (the right source, not just the right words) | deterministic, answer | `hr_compass/evaluation/domain/scores.py` → `score()` |
| `facts` | every `must` fact is in the answer | deterministic, answer | `scores.py` → `score()` |
| `abstain` / `false_abstain` | "I don't know" where the documents have no answer, and not where they do | deterministic, answer | `scores.py` → `score()`, `aggregate()` |
| `attributed` | every statement of the answer carries a valid source label | deterministic, faithfulness | `hr_compass/assistant/domain/answer.py` → `attribute()` |
| `judge` | the answer is correct against the reference (LLM-as-a-judge, prompt `prompts/judge-v3/correct.txt`) | LLM | `hr_compass/evaluation/application/judges.py` → `LlmJudge.correct()` |
| `grounded` | every claim of the answer is supported by its cited sources (prompt `prompts/judge-v3/grounded.txt`) | LLM, faithfulness | `judges.py` → `LlmJudge.grounded()` |
| calibration | agreement, false pass and false fail of the judge against `labels.json` | | `scores.py` → `calibrate()` |
| gate | every number vs the saved baseline (tolerance 0.05) and every case that regressed | threshold | `scores.py` → `gate()` |
| testset lint | quotes match chunks, facts are in the sources and the references, kinds are covered | deterministic, testset | `hr_compass/evaluation/domain/testset.py` → `lint()` |

## Results

| Path | Produced by |
|---|---|
| [`results/retrieval_eval.json`](results/retrieval_eval.json) | `hr-compass eval retrieval`: recall@5 / MRR / context tokens / ms per configuration, by kind |
| [`results/retrieval_baseline.json`](results/retrieval_baseline.json) | `eval retrieval --save-baseline`: what the CI gate compares against |
| [`results/answers/`](results/answers/) | `eval answers --models ... --judge`: per model, every answer with its scores (`.json`) and a report of the cases to read (`.md`), plus the comparison table |
| [`results/experiments/`](results/experiments/) | the chunking and embedding experiments (`config/experiments/*.toml`): chunk stats and retrieval per variant, local and provider embeddings |

Every result file records the `dataset_version` and the settings `fingerprint`, so a number can be traced to the exact
data and settings that produced it.

## Running

```bash
hr-compass eval lint                     # the testset matches the chunks (free)
hr-compass eval retrieval --gate         # retrieval quality vs the baseline (free, local models)
hr-compass eval answers --judge          # the real bot on every case + the judge (paid, OpenRouter)
hr-compass eval calibrate                # the judge vs labels.json (paid, ~$0.003)
```

CI (`.github/workflows/tests.yml`, job `evals`) runs the first two commands on every push and pull request. It fails
the run on any of these:
- a testset problem;
- a metric that drops by more than 0.05;
- a question that is no longer found;
- an access leak.
