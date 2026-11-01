# Comparison report — HR Compass

## 1. Task
HR Compass is an HR assistant for employees of "It Company" (sub-companies IT-Outsourcing and IT-Product). It answers
questions about vacations, holidays, pay, leave and policies **only from the employee handbook** of the employee's
country (USA, Ukraine, Costa Rica), cites the handbook sections it used, refuses (and refers to HR) when the handbook
has no answer, and asks for the country when it is unknown.

This report compares three cloud models and two answer-prompt versions on the same golden set.

## 2. Experimental setup
| Parameter | Value |
|---|---|
| Golden set | `data/golden_set.jsonl`, 40 questions: 10 questions × 3 country profiles (USA, UA, Costa Rica) + the same 10 without a profile. 8 of 10 questions in English, 2 in Ukrainian (q01, q07) |
| Knowledge base | `data/raw/`, 108 chunks: USA 58 (IT-Outsourcing + IT-Product), UA 25 (IT-Product), Costa Rica 25 (IT-Outsourcing; test set built from the UA handbook with 10 changed parameters) |
| Cloud models (OpenRouter) | `openai/gpt-4o-mini`, `anthropic/claude-haiku-5.5`, `deepseek/deepseek-v4.1-flash`; run with `--models`, so fallback is disabled and every answer comes from the model under test |
| Local model | not evaluated yet |
| Answer prompts | `v2_structured` (JSON answer: found / answer / sources / confidence); `v3_country_clarification` (v2 + explicit "answer language = question language" rule + "several countries in the context and no country named → ask for the country"; schema adds `needs_clarification`). See `prompts/CHANGELOG.md` |
| Pipeline | the same as the chat: intake (`intake_v2_en`: language, scope, country, clarification) → context → answer. The sample's `country` / `sub_company` is the employee profile known in advance (also passed to intake); a country named in the question takes precedence |
| Context | full context of the profile: all chunks of the employee's country (USA ~27k, UA / Costa Rica ~10.5k gpt-4o-mini tokens); without a profile — all three handbooks (~46k). No rerank |
| Sampling | `temperature=0.0`, `top_p=1.0`, `max_tokens=1024` (same for intake and answer) |
| Concurrency | 4 requests at a time |
| Run date | 2026-11-01 |

## 3. Metrics
- **Correct (keywords)** — share of the 30 questions with a profile whose reply contains all `expected_keywords`
  (case-insensitive substring). A failed call counts as wrong. Questions without a profile have no keywords.
- **Reply type** — share of all 40 questions where the reply kind (`answer` / `clarification`) equals `expected_kind`:
  `answer` for the 30 questions with a profile, `clarification` (ask for the country) for the 10 without one.
- **USA / UA / Costa Rica** — the keyword metric per country profile (10 questions each).
- **No country → clarification** — how many of the 10 questions without a profile got a clarifying question.
- **Language = question** — replies in the language of the question (heuristic: Cyrillic in the reply ⇔ Cyrillic in
  the question). Computed from `results.jsonl` by a separate script, not by `evaluate`.
- **Input / output tokens** — sum of `usage.prompt_tokens` / `usage.completion_tokens` over the run, intake included.
  Tokenizers differ: the same text is ~1.2–1.6× more tokens for Anthropic models than for gpt-4o-mini.
- **p50 / p95, s** — latency of one question (intake + answer), successful questions only, nearest-rank percentile.
- **Run cost** — actual cost, sum of `usage.cost` returned by OpenRouter (includes prompt-caching discounts).

## 4. Results
| Model | Prompt | Correct (keywords, 30 with profile) | Reply type (40) | USA | UA | Costa Rica | No country → clarification | Language = question | Input tokens | Output tokens | p50, s | p95, s | Succeeded | Run cost, $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-4o-mini | v2_structured | 86.7% (26/30) | 75.0% (30/40) | 70.0% (7/10) | 90.0% (9/10) | 100.0% (10/10) | 0.0% (0/10) | 95.0% (38/40) | 945 758 | 3 866 | 3.143 | 4.542 | 40/40 | 0.097642 |
| anthropic/claude-haiku-5.5 | v2_structured | 83.3% (25/30) | 87.5% (35/40) | 80.0% (8/10) | 90.0% (9/10) | 80.0% (8/10) | 60.0% (6/10) | 65.0% (26/40) | 1 169 967 | 21 286 | 4.557 | 7.401 | 40/40 | 0.12764 |
| deepseek/deepseek-v4.1-flash | v2_structured | 90.0% (27/30) | 75.0% (30/40) | 90.0% (9/10) | 90.0% (9/10) | 90.0% (9/10) | 30.0% (3/10) | 87.5% (35/40) | 883 833 | 30 410 | 3.546 | 9.165 | 40/40 | 0.04744 |
| openai/gpt-4o-mini | v3_country_clarification | 83.3% (25/30) | 77.5% (31/40) | 80.0% (8/10) | 80.0% (8/10) | 90.0% (9/10) | 10.0% (1/10) | 100.0% (40/40) | 964 718 | 4 271 | 3.049 | 4.529 | 40/40 | 0.095181 |
| anthropic/claude-haiku-5.5 | v3_country_clarification | **96.7% (29/30)** | **97.5% (39/40)** | 90.0% (9/10) | 100.0% (10/10) | 100.0% (10/10) | **100.0% (10/10)** | **100.0% (40/40)** | 1 117 881 | 20 047 | 4.337 | 7.659 | 40/40 | 0.121812 |
| deepseek/deepseek-v4.1-flash | v3_country_clarification | 93.3% (28/30) | 95.0% (38/40) | 90.0% (9/10) | 100.0% (10/10) | 90.0% (9/10) | **100.0% (10/10)** | **100.0% (40/40)** | 745 715 | 22 563 | **2.737** | **4.383** | 40/40 | **0.045037** |

Total cost of the six runs: **$0.53**. All 240 questions got a reply (no failed calls).

Runs (`results.jsonl`, `summary.json`, `table.md`), all in `results/runs/`:
- gpt-4o-mini — `20261101T132059Z_openai-gpt-4o-mini_v2_structured/`, `20261101T132319Z_openai-gpt-4o-mini_v3_country_clarification/`;
- haiku — `20261101T132154Z_anthropic-claude-haiku-5.5_v2_structured/`, `20261101T132407Z_anthropic-claude-haiku-5.5_v3_country_clarification/`;
- deepseek — `20261101T132243Z_deepseek-deepseek-v4.1-flash_v2_structured/`, `20261101T132436Z_deepseek-deepseek-v4.1-flash_v3_country_clarification/`;
- model comparison tables — `20261101T132243Z_compare_v2_structured.md`, `20261101T132436Z_compare_v3_country_clarification.md`;
  the consolidated table above — `results/summary.md`.

Cost per 1000 questions (run cost / 40 × 1000): deepseek-v4.1-flash $1.19 (v2) / $1.13 (v3), gpt-4o-mini $2.44 / $2.38,
claude-haiku-5.5 $3.19 / $3.05. It is also a column of `results/summary.md`.

### How to reproduce
One command runs the whole matrix (every prompt × every model) and rebuilds the consolidated table:

```bash
python scripts/run_all.py --prompts v2_structured,v3_country_clarification   # the six runs of this report
python scripts/run_all.py                    # default matrix: v2, v3, v4 × gpt4omini, haiku, deepseek (~$0.8)
python scripts/run_all.py --clean            # delete previous runs from results/runs/ first
python scripts/run_all.py --summary-only     # only rebuild results/summary.md from the existing runs
```

Each prompt is one `hr_compass.evaluate --models ...` call (fallback off, intake on, full context unless `--rerank`).
The script writes `results/summary.md` with one row per new run; it works without activating `.venv`.
See `README.md` → "The whole evaluation in one command" for all flags.

Notes (observations from `results.jsonl`, not conclusions):
- **Questions without a profile.** With v2 no model reliably asks for the country: the clarifications that happen
  (haiku 6, deepseek 3) all come from intake; otherwise the bot silently answers for one of the three countries.
  With v3 haiku and deepseek ask in 10/10 cases — intake asks in 6 / 4 of them, the v3 rule in the answer model catches
  the remaining 4 / 6. gpt-4o-mini ignores the v3 rule (1/10) and keeps answering for an arbitrary country.
- **Language.** With v2 English questions are often answered in Ukrainian (the prompt itself is in Ukrainian):
  haiku 14 of 40 replies, deepseek 5, gpt-4o-mini 2 (both refusals). With v3 all three models answer 40/40 in the
  language of the question.
- **Remaining errors with v3** (haiku 1, deepseek 2): q01 "how many vacation days" — intake asks for length of service /
  employment type instead of letting the answer list the conditions (USA allowance depends on both; the intake prompt
  names "length of service for vacation allowance" as its example). The reply kind is then `clarification`, which
  the metric counts as wrong.
- **gpt-4o-mini errors** are mostly incomplete answers: q06-usa (sick pay rate without the 40 hours), q08-usa
  (no answer although Paid Family Leave covers bonding), q03 (martial-law exception omitted / "3" missing), plus
  number-as-word false negatives (q06-ua "first five days").
- **Keyword check limits.** Single-digit keywords ("5", "6", "8") can match by chance; numbers written as words
  ("eight days", "шість тижнів") are counted as wrong. A reply that asks for clarification instead of answering is
  wrong for keywords too.
- **Structured output.** Invalid JSON happened a few times (haiku q07-usa, deepseek intake on several questions) and
  was fixed by the repair loop on the second attempt in every case.
- **Cost.** deepseek-v4.1-flash is ~2× cheaper than gpt-4o-mini and ~2.7× cheaper than haiku per run. Most tokens are
  the handbook in the context; the 10 questions without a profile (all three handbooks) are the most expensive ones
  unless intake stops them early.

## 5. Analysis
### Effect of the prompt version
### Comparison of models
### Cloud vs local model
### Error analysis

## 6. Conclusions
