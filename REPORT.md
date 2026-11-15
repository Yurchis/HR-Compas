# Comparison report — HR Compass

- **Part A — Retrieval (current, 2026-11-15):** a local and a provider embedding model, four chunkings and four
  search configurations, on the anonymised corpus and `data/testset.json`.
- **Part B — Answers on the RAG pipeline (current, 2026-11-15):** three answer models on `data/testset.json` with
  per-statement citations (prompt v6), deterministic scores and an LLM judge.
- **Appendix — Answer models before RAG (historical, 2026-11-01):** the whole handbook in the prompt and the retired
  golden set.

# Part A. Retrieval: local vs provider embeddings, chunking, search configuration

## A1. Setup
| Parameter | Value |
|---|---|
| Corpus | `data/data_dirty`: 41 files, of which 40 are indexed (1 XLSX is not supported). Anonymised before indexing: offers, personal PDPs, the contractor agreement and the employee spreadsheets were removed. Company names, people's names, e-mails, phones, the office address and personal payroll amounts were replaced in the rest. Public government contacts were kept |
| Questions | `data/testset.json`: 26 cases. The 23 answerable ones have known relevant chunks (labelled by quotes, so the labels survive re-chunking): paraphrase 11, exact 4, cross-lingual 4 (Ukrainian question, English document), access 2 (hr-only document), stale 2 (an archived handbook says otherwise). Each question is asked with the groups of its user |
| Embedding models | **local**: `paraphrase-multilingual-MiniLM-L12-v2` (fastembed, CPU, 384 dims, reads ~128 tokens, free, offline). **provider**: `openai/text-embedding-3-large` via OpenRouter `/embeddings` (3072 dims, reads ~8k tokens) |
| Chunkings | `headings` (split on headings, whole paragraphs / list items / table rows packed up to the limit) and `fixed` (sliding token window, 20-token overlap), each at 120 and 250 `cl100k` tokens |
| Search configurations | `vector` (Qdrant, cosine, access filter); `bm25`; `hybrid` (top-20 of both fused by RRF, k = 60); `hybrid+rerank` (the 20 hybrid candidates re-ordered by the local cross-encoder `ms-marco-MiniLM-L-6-v2`) |
| Metrics | recall@5 (a relevant chunk is in the top 5), MRR (1 / rank of the first relevant chunk), ctx tokens (mean tokens of the top 5, i.e. what the answer model reads), ms/query, leaks (hits the user may not read) |
| Configs and results | `config/experiments/<variant>.toml` (local) and `openrouter-<variant>.toml` (provider) → `results/experiments/<variant>/retrieval_eval.json` |

```bash
hr-compass --config config/experiments/openrouter-headings-120.toml run --no-chat         # ingest + embed + index
hr-compass --config config/experiments/openrouter-headings-120.toml eval retrieval --lenient
```

## A2. Results
recall@5 / MRR on the 23 questions. **Bold** marks the best value per embedding model. Leaks are 0 everywhere. No
chunking cut a testset quote, so every variant is measured on the same questions.

| Chunking | Config | Local MiniLM | Provider OpenAI 3-large |
|---|---|---|---|
| headings-120 | vector | 0.74 / 0.62 | **0.96 / 0.84** |
| | bm25 | 0.52 / 0.39 | 0.52 / 0.39 |
| | hybrid | 0.74 / 0.61 | 0.87 / 0.75 |
| | hybrid+rerank | **0.87 / 0.75** | 0.83 / 0.73 |
| fixed-120 | vector | 0.74 / 0.54 | 0.91 / 0.77 |
| | bm25 | 0.61 / 0.42 | 0.61 / 0.42 |
| | hybrid | **0.87** / 0.64 | 0.91 / 0.72 |
| | hybrid+rerank | 0.78 / 0.69 | 0.74 / 0.68 |
| headings-250 | vector | 0.70 / 0.64 | **0.96** / 0.81 |
| | bm25 | 0.57 / 0.42 | 0.57 / 0.42 |
| | hybrid | 0.74 / 0.62 | **0.96** / 0.76 |
| | hybrid+rerank | **0.87** / 0.72 | 0.83 / 0.72 |
| fixed-250 | vector | 0.61 / 0.49 | 0.91 / 0.80 |
| | bm25 | 0.65 / 0.47 | 0.65 / 0.47 |
| | hybrid | 0.74 / 0.60 | 0.91 / 0.76 |
| | hybrid+rerank | 0.78 / 0.69 | 0.78 / 0.69 |

**The best configuration of each model** (headings-120), recall@5 by question kind, context size and speed:

| | paraphrase (11) | exact (4) | cross-lingual (4) | access (2) | stale (2) | ctx tokens | ms/query | misses |
|---|---|---|---|---|---|---|---|---|
| local, hybrid+rerank | 1.00 | 1.00 | 0.50 | 1.00 | 0.50 | 438 | 568 | q17 q19 q23 |
| provider, vector | 1.00 | 0.75 | 1.00 | 1.00 | 1.00 | 447 | 904 | q15 |
| provider, hybrid+rerank | 1.00 | 1.00 | 0.25 | 1.00 | 0.50 | 454 | 1059 | q17 q19 q20 q23 |

**How the chunkings cut the corpus** (the same for both models):

| | headings-120 | fixed-120 | headings-250 | fixed-250 |
|---|---|---|---|---|
| chunks | 1769 | 1504 | 1034 | 665 |
| start mid-sentence | 95 (5 %) | 1045 (69 %) | 47 (5 %) | 451 (68 %) |
| table rows cut | 1 | 14 | 1 | 4 |
| without a section path | 13 | all | 9 | all |

**Cost of the provider model.** Embedding all four variants took 379 calls, ~505k tokens, **$0.066**. Embedding the
shipped corpus (headings-120) costs about $0.02 once; vectors are cached per model and text, so re-runs are free.
One search query costs ~$0.0000014 but adds a network round trip of ~0.9 s. The local model is free and answers a
vector query in ~65 ms on a laptop CPU.

## A3. Analysis
### Cloud vs local embedding model
The provider model is the largest single improvement in the project. Vector search goes from 0.74 / 0.62 to
**0.96 / 0.84** (+0.22 recall, +0.22 MRR), and it now finds 22 of 23 questions. The gain comes where the local model is
weak:
- **cross-lingual 0.75 → 1.00:** Ukrainian questions about English documents;
- **stale 0.50 → 1.00:** it tells the current handbook from the archived one;
- **paraphrase 0.82 → 1.00.**

Two reasons:
- it reads the whole chunk, while MiniLM silently drops everything after ~128 of its own tokens (57 headings-120
  chunks exceed even 120 `cl100k` tokens);
- it is much stronger on Ukrainian.

### Reranking
The local cross-encoder helps only weak embeddings. With MiniLM it lifts hybrid from 0.74 to 0.87 recall. With the
provider model it **lowers** quality, from 0.96 / 0.84 (vector) to 0.83 / 0.73. It is an English model: on the
cross-lingual questions it drops to 0.25 and pushes the right Ukrainian-question matches out of the top 5. A reranker
is worth keeping only if it is at least as good as the first stage. The multilingual OpenRouter reranker
(`[search].reranker = "openrouter"`) has not been measured yet.

### Hybrid (BM25)
- **With the local model**, BM25 does useful work: it is the only configuration with exact 1.00 (codes such as
  `DB-450`), and hybrid fixed-120 reaches 0.87.
- **With the provider model**, fusing in BM25 adds noise more often than signal. Hybrid headings-120 is 0.87 / 0.75
  against 0.96 / 0.84 for vector alone, because RRF lifts keyword matches over semantically better chunks.
- **The one remaining miss of provider vector** is q15, a one-word query ("Vchasno", a product name). This is the
  kind of query BM25 exists for, but RRF did not bring it into the top 5 either.

### Chunking
`headings-120` is the best or tied for best with both models, and it has the smallest context: about 440 tokens in
the top 5, against 590–1200 for the other chunkings. It keeps rules, lists and table rows whole and gives every chunk
its section, which the citations show. Fixed windows:
- start mid-sentence in about 70 % of chunks, cut table rows and have no section path;
- beat headings only with keyword-heavy configurations of the local model (bm25, hybrid);
- lose with the stronger model.

At 250 tokens, recall with the provider model stays the same (0.96), but the context grows by 1.5× (headings) to
2.7× (fixed). That is more tokens on every answer and less room in the 1500-token context budget.

### Error analysis
- **q15** (provider vector): a one-word query with a rare product name; dense vectors carry little meaning for a
  bare token.
- **q17, q19, q23** (local hybrid+rerank):
  - q17 and q23 are missed by every local configuration. q23 is a stale-kind question, where the archived handbook
    competes with the current one;
  - q19 is found by local vector and hybrid, but the reranker pushes it out of the top 5;
  - provider vector finds all three.
- **Access:** no configuration returned a chunk the asking user may not read (0 leaks, also in the dedicated access
  check as an ordinary employee).

### Limits of the measurement
- 23 questions are a small set. One question is 0.043 of recall, so differences of one or two questions are within
  noise. The large gaps (0.74 → 0.96 for vector, reranker −0.13 with the provider model) are not.
- This measures retrieval, not answers. Whether better retrieval gives better answers still has to be checked with
  `hr-compass eval answers`.

## A4. Conclusions
1. **Best quality: provider embeddings + headings-120 + `vector` mode without the reranker.** It gives 0.96 / 0.84
   recall@5 / MRR with the smallest context (447 tokens). It costs about $0.02 to index the corpus once, a negligible
   amount per query, and ~0.9 s of network latency. Chunk texts are sent to the provider, which is acceptable only
   because the corpus is anonymised.
2. **Best fully local setup (the current default): MiniLM + headings-120 + `hybrid+rerank`.** It gives 0.87 / 0.75 and
   is free, offline and private: no document text leaves the machine. Here the reranker and BM25 are what make it work.
3. **The reranker must match the embeddings.** Keep the local English cross-encoder only with the local model. With
   the provider model, turn it off or replace it with a multilingual one, and measure before switching.
4. **Chunking: headings-120 for both models.** Structure-aware chunks win or tie on recall, cost the least context and
   keep citations meaningful. Fixed windows are only a fallback for text without structure.
5. **Next steps:**
   - measure the OpenRouter (multilingual) reranker on top of provider vectors;
   - try hybrid with a lower BM25 weight to recover q15 without losing the rest;
   - re-measure the answers (Part B) on the RAG pipeline with the chosen retrieval.

# Part B. Answers on the RAG pipeline

## B1. Setup
| Parameter | Value |
|---|---|
| Pipeline | the chat's own `AskQuestion` (sequence below) |
| Retrieval | the shipped default from Part A: local MiniLM + headings-120 + `hybrid+rerank`, top 5, context budget 1500 `o200k` tokens |
| Questions | `data/testset.json`: 26 cases, 23 answerable plus 3 `no_answer` (the documents do not say; the bot must not invent) |
| Answer prompt | `prompts/v6_rag_cited.md` (CHANGELOG): only the sources, a `[S1]` label after every statement, "not found" when the sources do not answer |
| Models | `openai/gpt-4o-mini`, `anthropic/claude-haiku-5.5`, `deepseek/deepseek-v4.1-flash` via OpenRouter, fallback off, `temperature=0` |
| Judge | `prompts/judge-v3` (gpt-4o-mini). **judge**: correctness against the reference answer. **grounded**: every claim is supported by the cited sources. Calibrated against 30 hand-labelled answers: 0.93 agreement (B4, "Judge calibration") |
| Command | `hr-compass eval answers --models gpt4omini,haiku,deepseek --judge` → `results/answers/20261115-202124_*` |

The pipeline:
1. intake (language, scope, country);
2. condense (follow-up questions only);
3. retrieval;
4. context with `[S1]` labels;
5. answer;
6. citation check.

## B2. Metrics
| Metric | Meaning |
|---|---|
| pass | answerable: `facts` and `cited`. no_answer: `abstain` |
| facts | every `must` fact is in the answer |
| cited | a relevant chunk is among the cited ones |
| attributed | share of found answers in which **every statement** carries a valid source label (new in v6, not part of pass) |
| abstain | no_answer cases where the bot said it has no information |
| false abstain | answerable cases where the bot gave up |
| judge / grounded | the LLM judge, see B1 |
| input / output tokens | sum of `usage.prompt_tokens` / `usage.completion_tokens` over the run, intake and answer calls (judge excluded) |
| $ / run, p50 / p95 | actual cost reported by OpenRouter; latency of one question, nearest-rank percentile |

## B3. Results
| Model | pass | facts | cited | attributed | abstain | false abstain | judge | grounded | Input tokens | Output tokens | $ / run | p50, s | p95, s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-4o-mini | 0.77 | 0.78 | 0.74 | **1.00** | **1.00** | 0.17 | 0.73 | 0.84 | 48 111 | **2 059** | **0.0085** | **3.41** | 11.17 |
| anthropic/claude-haiku-5.5 | **0.88** | **0.91** | **0.87** | 0.71 | **1.00** | **0.09** | 0.81 | 0.67 | 91 169 | 12 816 | 0.0155 | 4.55 | **6.89** |
| deepseek/deepseek-v4.1-flash | 0.85 | 0.87 | 0.83 | **1.00** | **1.00** | 0.13 | **0.85** | **1.00** | **44 314** | 11 950 | 0.0131 | 3.90 | 11.12 |

**Tokens.**
- **What is counted:** `usage.prompt_tokens` / `usage.completion_tokens` as OpenRouter returns them, summed over the
  26 questions. Each question includes intake and the answer call. The judge calls are not included: the judge is
  gpt-4o-mini, $0.014 for the run.
- **Per question:**

  | Model | input tokens | output tokens |
  |---|---|---|
  | gpt-4o-mini | ~1 850 | ~80 |
  | haiku | ~3 500 | ~490 |
  | deepseek | ~1 700 | ~460 |

- **Input is mostly the sources:** at most 1500 tokens of context, plus the system prompts. This is why input per
  question is about the same for every model.
- **haiku's input looks about twice as large,** largely because Anthropic's tokenizer counts the same text as more
  tokens (the appendix measured 1.2–1.6×).
- **Output differs about 6×.** gpt-4o-mini writes the shortest JSON. haiku and deepseek produce several hundred
  output tokens per question, so for them output is a large part of the cost.

pass by question kind:

| Model | paraphrase (11) | exact (4) | cross-lingual (4) | access (2) | stale (2) | no_answer (3) |
|---|---|---|---|---|---|---|
| gpt-4o-mini | 1.00 | 0.25 | 0.50 | 1.00 | 0.50 | 1.00 |
| claude-haiku-5.5 | 1.00 | 1.00 | 0.50 | 1.00 | 0.50 | 1.00 |
| deepseek-v4.1-flash | 1.00 | 0.75 | 0.50 | 1.00 | 0.50 | 1.00 |

The run cost $0.037 for the three models plus $0.014 for the judge, **$0.051** in total. One answer costs about
$0.0003–0.0006. Example of an answer with sources: see README, "How a question is answered".

## B4. Analysis
### "I don't know" instead of invention
All three models abstained on all three `no_answer` questions (abstain 1.00), for example "can I bring a dog to the
office" or "13th-month salary". The guards work as designed:
- no readable chunk → no answer call;
- the prompt rule "no answer in the sources → `found=false`";
- an answer without a valid citation → "not found".

The cost is false abstentions (0.09–0.17): answerable questions where the bot said "not found" or refused. They
come from two places upstream of the answer model:
- retrieval misses: q17 and q19, all three models;
- intake refusing a bare code: q13, q15, q16 for gpt-4o-mini and q13 for deepseek.

See the error analysis.

### Per-statement citations
- **gpt-4o-mini and deepseek** label every statement (attributed 1.00), and deepseek is also fully grounded
  (grounded 1.00).
- **haiku** most often adds a sentence of its own without a label (attributed 0.71), for example "These rules are
  listed for Ukraine" or "other countries may differ". The judge finds the same sentences not supported by the
  sources (grounded 0.67).

So unlabelled statements and ungrounded statements are the same problem. The `attributed` metric finds it for free,
without a judge call.

### Comparison of models
- **haiku** has the most correct answers (pass 0.88, facts 0.91) and the best tail latency. It is also the least
  disciplined about sources.
- **deepseek** is the best balance: pass 0.85, judge 0.85, grounded 1.00, attributed 1.00, at 1.5× the cost of
  gpt-4o-mini.
- **gpt-4o-mini** is the cheapest and fastest at p50. It loses mainly on bare-code questions (exact 0.25): its intake
  marks "DB-450", "Vchasno" and "Speaking Club" as out of scope, so it never searches.

### Token savings from RAG
**1. Measured: the previous bot (whole handbook in the prompt) vs RAG.** Old numbers are prompt v3, 40 questions,
from the appendix. New numbers are prompt v6, 26 questions, from B3.

| Model | Input tokens per question: before → RAG | Input saved | Cost per question: before → RAG |
|---|---|---|---|
| gpt-4o-mini | ~24 100 → ~1 850 | **−92 % (13×)** | $0.0024 → $0.0003 (7× cheaper) |
| claude-haiku-5.5 | ~27 900 → ~3 500 | **−87 % (8×)** | $0.0030 → $0.0006 (5× cheaper) |
| deepseek-v4.1-flash | ~18 600 → ~1 700 | **−91 % (11×)** | $0.0011 → $0.0005 (2.2× cheaper) |

- **Cost falls less than input tokens.** Output tokens are not reduced, and deepseek writes more of them now.
- **Latency did not improve.** p50 is about 3–4 s in both versions, because retrieval with the local reranker adds
  ~0.6 s per question.
- **Caveat:** the question sets and corpora differ (then 3 handbooks, 108 chunks; now 40 documents, 1769 chunks).
  Read this as an order of magnitude, not a controlled experiment.

**2. Computed: the current corpus in the prompt vs RAG.** Calculated from `chunks.jsonl`, no model calls.

| Context per question | Tokens |
|---|---|
| every document an ordinary employee may read | ~46 300 |
| every document HR may read | ~149 000: **does not fit** gpt-4o-mini's 128k context |
| RAG: top 5 chunks | **≤ 1 500** (≈ 440 on average) |

RAG sends **~30× fewer input tokens** than "everything the employee may read" and **~100× fewer** than everything HR
may read. With gpt-4o-mini that is about $0.007 vs $0.0003 per question, ~20× cheaper. For HR, the whole corpus
cannot be sent to the model at all, so retrieval is required, not just cheaper.

### Error analysis
Most failures come from the steps before the answer model, not from the model itself:

| Cause | Cases | Models | Fix |
|---|---|---|---|
| retrieval miss: the right chunk is not in the top 5 | q17, q19 (Ukrainian questions), q23 (stale: the archived handbook ranks above the current one) | all three | provider embeddings (Part A: vector 0.96, cross-lingual and stale 1.00) |
| intake refuses a bare code as out of scope | q13 `DB-450`, q15 `Vchasno`, q16 `Speaking Club` | gpt-4o-mini (3), deepseek (1) | intake prompt: a code, form or product name alone is in scope |
| a PDF table lost its columns | q11: the vacation FAQ compares "Current Policy / New Policy" in two columns; the extracted text runs them together, so "0–3 years: 80 hrs" has no column, while the handbook says 92 hours | gpt-4o-mini, haiku | extract PDF tables with their columns, or mark the old policy in the document |
| judge false negative | q01: the answer has both rules (1 day up to 3 years, 2 days after) but is judged incorrect | haiku, deepseek | judge-v3 is strict on extra details; read the case before acting |

### Judge calibration
The judge was checked against **30 answers labelled by hand** (`data/labels.json`, `hr-compass eval calibrate`,
$0.0026).
- **Which answers:** real answers of this run. Every case once with the three models in rotation, plus 4 cases where
  the scores disagree.
- **How they were labelled:** the author labelled them blind, with the question, the reference and the answer
  visible and the judge's verdict hidden. Result: 21 correct, 9 incorrect.
- **One exception:** one answer left unlabelled (q13-gpt4omini, a refusal of an answerable question) was set to
  incorrect and marked in its `note`.

| Verdict vs the person | agreement | false pass | false fail | disagreements |
|---|---|---|---|---|
| deterministic `pass` (facts + cited) | 0.93 (28/30) | 0.07 | 0.00 | q11-haiku, q11-gpt4omini |
| LLM judge (`judge-v3/correct`) | **0.93 (28/30)** | 0.03 | 0.03 | q23-deepseek, q01-haiku |
| both: `pass` **and** judge correct | **0.97 (29/30)** | **0.00** | 0.03 | q01-haiku |
| LLM judge, after fixing the q02 / q23 references (see below) | **1.00 (30/30)** | 0.00 | 0.00 | – |

- **The judge agrees with the person on 93 % of answers.** This is in line with the 0.92 on 90 answers measured for
  judge-v3 in lesson 9, now on this bot's own answers.
- **Its false pass (q23-deepseek):** an answer faithful to the **archived** handbook. The judge's own reason shows
  the cause: "the key fact is that eligibility for remote work starts after 1 year of service, which the reference
  confirms". The reference mentions the outdated rule, to explain the trap ("the archived 2025 handbook started
  remote days only after 1 year"), and the judge took that clause as the expected fact. This is a testset wording
  problem, not only a judge one.
  - Fix: state only the current rule in the reference, and put the trap in a separate field the judge does not
    read.
  - **Done** for q02 and q23: `reference` holds only the current answer, and the outdated value moved to a new
    `trap` field. Re-running `eval calibrate`, $0.0026, the judge failed the archived answer and agreed with the
    person on **30/30**.
  - q01-haiku also flipped to "correct", although its reference did not change. The judge is not perfectly stable
    from run to run, so 0.93–1.00 is the honest range of its agreement on this set.
  - The archived handbooks also say "eligible for remote work following 60 days", so the reference's description of
    them is inaccurate too.
- **Its false fail (q01-haiku):** a complete answer that adds the weekdays. judge-v3 is strict about extra details.
- **The deterministic `pass` never fails a correct answer.** It passes the two q11 answers that contain "11.5 days"
  next to a wrong number of hours: a keyword match cannot see a contradiction.
- **The two kinds of errors do not overlap.** Requiring both checks removes every false pass (0.97 agreement, 0 false
  pass), at the cost of one false fail. A gate built on `pass` + judge therefore never lets a wrong answer through on
  this set.
- **Limits:** one labeller and 30 answers. One answer is 0.033 of agreement.

### Characteristic errors: expected → got → why
Five real answers from the run (`results/answers/20261115-202124_*`), one per kind of failure.

**1. Stale trap: an outdated handbook wins** (q23, haiku and deepseek)
- **Question:** "I joined three months ago. Can I already work from home?"
- **Expected:** yes, one day a week (Wednesday or Thursday), from the current handbook (2026). The archived 2025
  handbook allowed remote days only after 1 year.
- **Got (deepseek):** "No — under the remote work policy, eligibility starts at 1 year of service… [1]". Its source
  [1] is `Handbook_Revised 03.21.25.pdf`, the **archived** handbook.
- **Why:**
  - The question is asked by a user with the `hr` group, who may read the archive.
  - Retrieval ranked the archived chunk above the current one. q23 is a miss in every local configuration in Part A.
  - The prompt rule "the newer source wins" cannot work when only the old version is in the context.
  - The judge marked the answer **correct**, misled by the reference, which mentions the outdated rule (see "Judge
    calibration"). The groundedness check passed too: the answer *is* faithful, to an outdated source. Only the
    deterministic `cited` check (a relevant, i.e. current, chunk among the cited ones) caught it.
- **Fix:**
  - keep `Archive/` out of answer retrieval unless the question asks about history;
  - provider embeddings find the current chunk (Part A: stale 1.00).

**2. Cross-lingual: the neighbouring chunk is retrieved and misread** (q17, gpt-4o-mini)
- **Question:** "Скільки днів на тиждень можна працювати з дому?"
- **Expected:** one day a week up to 3 years of service, two days after.
- **Got:** "до 2 днів на тиждень, якщо менше 1 року стажу, до 3 днів… до 5 днів… [1]".
- **Why:**
  - The Ukrainian query retrieved chunk #106 of the same section (*extra* remote days, "no more than 2 / 3 / 5
    consecutive days") instead of #105, which holds the weekly rule. The headings chunking split the section into
    two chunks, and local MiniLM matched the wrong half.
  - The model then read "consecutive days" as "days per week".
  - The groundedness check passed: every number is in the source, only misinterpreted. The `facts` check failed it
    correctly.
  - haiku and deepseek did not get #105 either and said "not found".
- **Fix:**
  - provider embeddings (Part A: cross-lingual 1.00);
  - keep a section's introduction and its lists in one chunk: at 250 tokens the weekly rule and the extra days share
    a chunk in 4 handbook versions, at 120 tokens in only 1.

**3. Intake refuses a bare code** (q13, gpt-4o-mini; the same for deepseek)
- **Question:** "DB-450"
- **Expected:** the short-term disability claim form: get it from HR and send it to NYSIF.
- **Got:** "I only answer questions about working at the company. Please contact HR with this one."
- **Why:** intake (`intake_v3_en.md`) classified a form code with no verb as out of scope, so the bot never
  searched. Retrieval would have found it: exact questions score 1.00 in hybrid+rerank.
- **Fix:** an intake rule (intake v4) that a code, form or product name on its own is in scope.

**4. Numbers mixed from two sources** (q11, gpt-4o-mini)
- **Question:** "How much vacation do US employees accrue per year during their first three years?"
- **Expected:** 1.77 hours a week, 92 hours (11.5 days) a year.
- **Got:** "11.5 days (80 hours) of vacation per year [1, 2]". "11.5 days" comes from the handbook (92 hours), and
  "80 hours" from the vacation FAQ.
- **Why:**
  - The FAQ PDF compares "Current Policy / New Policy" in two columns. The extracted text runs the columns together,
    so "0–3 years: 80 hrs (10 days)" no longer says which policy it belongs to.
  - The model merged the two sources into one inconsistent figure.
  - The `facts` check passed it ("11.5 days" is present), a false pass of the deterministic score. The judge marked
    it incorrect.
- **Fix:**
  - extract PDF tables with their columns, or mark the old policy in the document;
  - add "92 hours" to the case's `must` facts.

**5. A statement without a source** (q13, haiku)
- **Expected:** every statement carries its source label.
- **Got:** "DB-450 is the short-term disability claim form, which you can get from Human Resources. Send the
  completed form to NYSIF… [1]. The payroll checklist also links to this form… [2]".
  - The first sentence has no label (`attributed` = false).
  - The groundedness judge rejected the last claim ("the payroll checklist links to this form") as not supported by
    its source.
- **Why:** haiku adds connective and commentary sentences, and does not always follow the "label every statement"
  rule (attributed 0.71 overall).
- **Fix:**
  - repair the answer when a statement has no label (one more call asking for labels), or drop unlabelled sentences;
  - prefer deepseek (attributed 1.00, grounded 1.00).

**What these errors show about the checks.**
- No single score is enough: the judge passed error 1, groundedness passed errors 1 and 2, and `facts` passed
  error 4.
- The deterministic `cited` and `attributed` checks and the LLM judge catch different failures, so the report keeps
  all of them.

### Effect of the prompt version (v5 → v6)
v6 changes only how sources are cited, and v6 runs give attributed 1.00 / 1.00 / 0.71. Under v5 the answers carry no
inline labels at all, so attributed would be 0 by construction. A v5 run on the same 26 cases to confirm that pass,
facts and abstain did not drop is not measured yet:

```bash
hr-compass --config config/experiments/answers-v5.toml eval answers --judge \
  --models openai/gpt-4o-mini,anthropic/claude-haiku-5.5,deepseek/deepseek-v4.1-flash
```

## B5. Conclusions
1. **The answer contract is met.**
   - Answers are built only from the retrieved chunks.
   - Every statement cites its source, and the chat lists them as `[n] <document> — <section>`.
   - The context fits a 1500-token budget.
   - The bot says "not found" instead of inventing: abstain 1.00 for every model.
2. **Recommended answer model: deepseek-v4.1-flash** (pass 0.85, grounded 1.00, attributed 1.00, $0.0005 per
   answer). haiku is more often right but adds unsourced remarks. gpt-4o-mini is cheapest but its intake refuses bare
   codes.
3. **The next quality gain is in retrieval and intake, not in the answer model.**
   - Switch to provider embeddings (Part A). This fixes the cross-lingual and stale misses that cause most false
     abstentions.
   - Let intake accept a bare code or product name.
4. **Data and ingestion:**
   - keep the archived handbooks out of answer retrieval (error 1);
   - extract PDF tables with their columns, so a "Current vs New policy" table keeps its meaning (error 4).
5. **The judge can be trusted, with one blind spot.** It agrees with hand labels on 93 % of 30 answers. It follows
   the reference literally: a reference that mentions an outdated value (q23) made it pass an outdated answer.
   Combined with the deterministic `pass` it reaches 97 % with no false pass, so release decisions should use both
   (`pass` and judge), not either alone. References should state only the expected answer.
6. **RAG cuts input tokens roughly 10×** against the previous whole-handbook prompt (−87…−92 %, 2–7× cheaper per
   question) and **30–100×** against putting the current corpus in the prompt. HR's corpus (~149k tokens) would not
   fit the model's context at all. The latency is about the same, because retrieval and reranking take ~0.6 s.

# Appendix. Answer models before RAG (historical)

> **Historical (2026-11-01).** The numbers below were measured on the previous version: the whole country handbook
> (`data/raw`, now deleted) in the prompt and `data/golden_set.jsonl` (retired). The scripts and paths named here no
> longer exist. They are kept as the record of the prompt work v1–v4 (`prompts/CHANGELOG.md`). Current answers: Part B.

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
