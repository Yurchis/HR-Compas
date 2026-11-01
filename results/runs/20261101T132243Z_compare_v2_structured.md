# Model comparison, prompt `v2_structured`

| Model | Prompt version | Sampling | Price, $/1M (in/out) | Correct, % | Reply type, % | Input tokens | Output tokens | p50, s | p95, s | Succeeded | Run cost, $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-4o-mini | v2_structured + intake_v2_en | temperature=0.0, top_p=1.0 | 0.15 / 0.6 | 86.7% (26/30) | 75.0% (30/40) | 945 758 | 3 866 | 3.143 | 4.542 | 40/40 | 0.097642 |
| anthropic/claude-haiku-5.5 | v2_structured + intake_v2_en | temperature=0.0, top_p=1.0 | 0.1 / 0.5 | 83.3% (25/30) | 87.5% (35/40) | 1 169 967 | 21 286 | 4.557 | 7.401 | 40/40 | 0.12764 |
| deepseek/deepseek-v4.1-flash | v2_structured + intake_v2_en | temperature=0.0, top_p=1.0 | 0.045 / 0.5 | 90.0% (27/30) | 75.0% (30/40) | 883 833 | 30 410 | 3.546 | 9.165 | 40/40 | 0.04744 |
