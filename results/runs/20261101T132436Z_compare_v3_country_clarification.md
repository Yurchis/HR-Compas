# Model comparison, prompt `v3_country_clarification`

| Model | Prompt version | Sampling | Price, $/1M (in/out) | Correct, % | Reply type, % | Input tokens | Output tokens | p50, s | p95, s | Succeeded | Run cost, $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-4o-mini | v3_country_clarification + intake_v2_en | temperature=0.0, top_p=1.0 | 0.15 / 0.6 | 83.3% (25/30) | 77.5% (31/40) | 964 718 | 4 271 | 3.049 | 4.529 | 40/40 | 0.095181 |
| anthropic/claude-haiku-5.5 | v3_country_clarification + intake_v2_en | temperature=0.0, top_p=1.0 | 0.1 / 0.5 | 96.7% (29/30) | 97.5% (39/40) | 1 117 881 | 20 047 | 4.337 | 7.659 | 40/40 | 0.121812 |
| deepseek/deepseek-v4.1-flash | v3_country_clarification + intake_v2_en | temperature=0.0, top_p=1.0 | 0.045 / 0.5 | 93.3% (28/30) | 95.0% (38/40) | 745 715 | 22 563 | 2.737 | 4.383 | 40/40 | 0.045037 |
