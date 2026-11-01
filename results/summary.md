# Evaluation summary

Golden set: `data/golden_set.jsonl`. Intake: `intake_v2_en`. Metric definitions: `REPORT.md`, section 3. "Language = question" and the per-country columns are computed here from `results.jsonl`; "Cost per 1000 questions" = run cost / questions × 1000.

| Model | Prompt | Context | Sampling | Correct (keywords) | Reply type | USA | UA | Costa Rica | No country → clarification | Language = question | Input tokens | Output tokens | p50, s | p95, s | Succeeded | Run cost, $ | Cost per 1000 questions, $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anthropic/claude-haiku-5.5 | v2_structured | full | t=0.0, top_p=1.0 | 83.3% (25/30) | 87.5% (35/40) | 80.0% (8/10) | 90.0% (9/10) | 80.0% (8/10) | 60.0% (6/10) | 65.0% (26/40) | 1 169 967 | 21 286 | 4.557 | 7.401 | 40/40 | 0.12764 | 3.19 |
| deepseek/deepseek-v4.1-flash | v2_structured | full | t=0.0, top_p=1.0 | 90.0% (27/30) | 75.0% (30/40) | 90.0% (9/10) | 90.0% (9/10) | 90.0% (9/10) | 30.0% (3/10) | 87.5% (35/40) | 883 833 | 30 410 | 3.546 | 9.165 | 40/40 | 0.04744 | 1.19 |
| openai/gpt-4o-mini | v2_structured | full | t=0.0, top_p=1.0 | 86.7% (26/30) | 75.0% (30/40) | 70.0% (7/10) | 90.0% (9/10) | 100.0% (10/10) | 0.0% (0/10) | 95.0% (38/40) | 945 758 | 3 866 | 3.143 | 4.542 | 40/40 | 0.097642 | 2.44 |
| anthropic/claude-haiku-5.5 | v3_country_clarification | full | t=0.0, top_p=1.0 | 96.7% (29/30) | 97.5% (39/40) | 90.0% (9/10) | 100.0% (10/10) | 100.0% (10/10) | 100.0% (10/10) | 100.0% (40/40) | 1 117 881 | 20 047 | 4.337 | 7.659 | 40/40 | 0.121812 | 3.05 |
| deepseek/deepseek-v4.1-flash | v3_country_clarification | full | t=0.0, top_p=1.0 | 93.3% (28/30) | 95.0% (38/40) | 90.0% (9/10) | 100.0% (10/10) | 90.0% (9/10) | 100.0% (10/10) | 100.0% (40/40) | 745 715 | 22 563 | 2.737 | 4.383 | 40/40 | 0.045037 | 1.13 |
| openai/gpt-4o-mini | v3_country_clarification | full | t=0.0, top_p=1.0 | 83.3% (25/30) | 77.5% (31/40) | 80.0% (8/10) | 80.0% (8/10) | 90.0% (9/10) | 10.0% (1/10) | 100.0% (40/40) | 964 718 | 4 271 | 3.049 | 4.529 | 40/40 | 0.095181 | 2.38 |

Total cost of these runs: $0.5348

Run directories (`results/runs/`):
- anthropic/claude-haiku-5.5 / v2_structured / full / t=0.0, top_p=1.0 — `20261101T132154Z_anthropic-claude-haiku-5.5_v2_structured/`
- deepseek/deepseek-v4.1-flash / v2_structured / full / t=0.0, top_p=1.0 — `20261101T132243Z_deepseek-deepseek-v4.1-flash_v2_structured/`
- openai/gpt-4o-mini / v2_structured / full / t=0.0, top_p=1.0 — `20261101T132059Z_openai-gpt-4o-mini_v2_structured/`
- anthropic/claude-haiku-5.5 / v3_country_clarification / full / t=0.0, top_p=1.0 — `20261101T132407Z_anthropic-claude-haiku-5.5_v3_country_clarification/`
- deepseek/deepseek-v4.1-flash / v3_country_clarification / full / t=0.0, top_p=1.0 — `20261101T132436Z_deepseek-deepseek-v4.1-flash_v3_country_clarification/`
- openai/gpt-4o-mini / v3_country_clarification / full / t=0.0, top_p=1.0 — `20261101T132319Z_openai-gpt-4o-mini_v3_country_clarification/`
