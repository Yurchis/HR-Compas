# Prompt changelog

Every prompt version is a separate file in `prompts/` (e.g. `v1_<name>.md`).
Published versions are never edited: a change = a new version + an entry below.

<!-- Entry template:
## vN — `vN_<name>.md` (YYYY-MM-DD)
**Hypothesis:** ...
- what changed
- expected effect
-->

## v1 — `v1_baseline.md` (2026-10-26)
**Hypothesis:** the full handbook in the context + a strict ban on making things up gives accurate answers with source references.
- first version: answer only from the handbook, in the language of the question, with conditions of application and sources `[id]`
- expected effect: a baseline for comparing the next versions

## v2 — `v2_structured.md` (2026-10-26)
**Hypothesis:** requiring a JSON schema (found/answer/sources/confidence) gives machine-checkable answers and fewer made-up ones.
- the answer is JSON by the schema in `hr_compass/schema.py`; sources and confidence are separate fields
- for `found=false` a refusal with a referral to HR is spelled out explicitly
- v1 stays for comparison (run with `structured_output.enabled = false`)

## v3 — `v3_country_clarification.md` (2026-11-01)
**Hypothesis:** if the employee's country is unknown and the context holds the rules of several countries, a model
without an explicit rule silently picks one of them (gpt-4o-mini run 2026-11-01: 10/10 `qNN-any` questions answered for
an arbitrary country). An explicit rule "several countries in the fragments and no country named → a clarifying
question" removes such wrong answers. Separately: refusals in Ukrainian to English questions (1/8 per run with v2) should
disappear thanks to an explicit language rule.
- based on v2; a new answer schema `hr_answer_v3` (`hr_compass/schema.py`, `HRAnswerV3`): the `needs_clarification`
  field; when `true` — `found=false`, `sources=[]`, and `answer` holds the question about the country. The pipeline
  returns such a reply as `clarification` (in `evaluate` — the "Reply type" column)
- a separate "Answer language" block: the language of `answer` = the language of the question, for an answer, a refusal
  and a clarification; the language of the instructions and of the handbook does not matter
- the schema is set by the first line of the file `<!-- schema: hr_answer_v3 -->` (the model does not see it); v1/v2 unchanged
- expected effect: `qNN-any` → `clarification` (reply type ~100%), answer language = question language; accuracy on
  questions with a profile — as with v2. Cost does not go down: the context for `qNN-any` is all three handbooks

## v4 — `v4_country_clarification_en.md` (2026-11-01)
**Hypothesis:** as with intake v2, models follow instructions in English more precisely and with fewer tokens;
an English prompt also does not pull answers to English questions into Ukrainian (with v2 this was up to 14/40 for haiku).
- a literal English translation of v3; the rules (answer language, country clarification), the `hr_answer_v3` schema
  and the JSON example are unchanged
- v3 stays unchanged: the runs in `REPORT.md` (2026-11-01) were made with it
- expected effect: the same or better results than v3, fewer input tokens per call

## intake v1 — `intake_v1.md` (2026-10-27; file renamed from `intake_promt.md` on 2026-11-15 to follow the naming scheme, content unchanged)
**Hypothesis:** a separate cheap call that determines the language, the topic and the employee profile makes it possible not to run off-topic questions through the handbook (~30k tokens) and to narrow the context by country/sub-company.
- output — JSON by `hr_compass/intake.py` (`language`, `in_scope`, `country`, `sub_company`, `needs_clarification`, `clarifying_question`)
- country/sub-company are filled only if named explicitly; a clarification — only when without it the answer would be wrong
- does not change the answer prompts v1/v2

## intake v2 — `intake_v2_en.md` (2026-10-31)
**Hypothesis:** models follow instructions in English more precisely and with fewer tokens than in Ukrainian.
- a literal English translation of intake v1; fields, values and rules unchanged
- `chat.py` uses v2 by default; v1 is available via `--intake-prompt prompts/intake_v1.md`
- expected effect: the same classification, fewer tokens per call

## judge v3 — `judge-v3/correct.txt`, `judge-v3/grounded.txt` (2026-11-14)
**Hypothesis:** an LLM judge that compares only the key fact the question asks for (not every detail of the reference) grades answers that `must` lists cannot: yes/no, paraphrases, Ukrainian answers to English references.
- taken unchanged from lesson 9 (`prompts/judge-v3`), where it agreed with people on 0.92 of 90 hand-labelled answers (0.99 after one reference was fixed); v1/v2 were its earlier calibration steps there
- used by `hr_compass/rag_eval.judge`; the reply is JSON by `Verdict` (reason first, then `correct`/`incorrect`)
- not yet calibrated on HR Compass answers: needs answers labelled by a person (`calibrate`); a live smoke test (`HR_COMPASS_LIVE=1`) passes 5/5 on gpt-4o-mini: right, wrong number, Ukrainian answer, correct abstain, invented answer to a no_answer case
- `grounded.txt` (lesson 9, unchanged): splits the answer into claims and marks each supported or not by the cited sources; used by `hr_compass/rag_eval.grounded` (JSON by `Claims`). Live smoke test on gpt-4o-mini: a faithful and a Ukrainian answer are grounded; an added rule ("can be extended by 2 months") and a wrong number are caught

## Retired with the handbook — v1–v4, intake v1–v2 (2026-11-15)
The old knowledge base (`data/raw/*.json`, one country-tagged handbook per country) was deleted; the bot now answers
from the documents in `data/data_dirty` through retrieval (RAG). v1–v4 and intake v1–v2 stay here as history: they
expect the whole handbook in the system prompt (`{{context}}`) and an `It Company` with sub-companies, so they do not
run on the RAG context.

## v5 — `v5_rag.md` (2026-11-15)
**Hypothesis:** answering only from the retrieved sources, each under a label (`[S1] title · section · country ·
effective date`), with citations checked by code, keeps the answers grounded on a corpus of 1989 chunks that no
longer fits a prompt.
- based on the lesson 8 RAG prompt (only the sources; "discontinued / does not apply" is an answer; the newer source
  wins; numbers copied exactly) plus v4's rules: the answer in the question's language, and a clarifying question when
  the sources hold rules of several countries and no country is known
- JSON `{found, answer, citations, confidence, needs_clarification}` (`assistant.domain.answer.RagAnswer`); a label the
  model was not shown is dropped, and an answer with no valid citation becomes "not found"
- the sources go in the user message (`<sources>`), not in the system prompt: the system prompt is the same for every
  question
- smoke run (5 cases, gpt-4o-mini): pass 5/5, $0.0013

## v6 — `v6_rag_cited.md` (2026-11-15)
**Hypothesis:** a source label after every statement ("... 24 days [S1].") makes each claim checkable against its
document and section, instead of one source list for the whole answer.
- v5 plus: every sentence ends with the label(s) of its sources before the full stop, `[S1]` or `[S1, S3]`; no
  statement without a source; the replaced value in rule 2 is cited too; the JSON example shows inline labels
- code (`assistant.domain.answer.attribute`): unknown labels are dropped from the text and the list; the labels are
  renumbered `[1]`, `[2]` in the order the chat lists the sources (`Sources: [1] <document> — <section>`); statements
  without a valid label are counted (`Reply.uncited_statements`, warned in the log)
- new metric `attributed` in `eval answers`: the share of found answers in which every statement names its source
  (reported, not part of `pass`)
- expected effect: `attributed` close to 1.0 with no loss of pass / facts / abstain against v5
## intake v3 — `intake_v3_en.md` (2026-11-15)
**Hypothesis:** intake v2 without the deleted `It Company` / sub-companies classifies questions about the new corpus
as well, and a broad "in scope" keeps HR tool questions from being refused.
- the company has employees in the USA, Ukraine and Costa Rica; `country` from the question only; no `sub_company`
- the country alone is not a reason to ask back (the answer step handles several countries)
- in scope includes the HR tools and their rules (BambooHR, the profile photo, time-off requests); when in doubt, in
  scope: the answer step says when the documents do not cover it. The first draft refused "What should the background
  of my profile picture look like?" as out of scope (smoke run 4/5); with this rule 5/5

## condense v1 — `condense_v1.md` (2026-11-15)
**Hypothesis:** a follow-up ("and after 3 years?") searched as it is finds nothing; rewritten with the dialog into a
standalone question it finds the same chunks as a full question.
- the lesson 8 condense prompt, answering JSON `{question}` like every other call (structured output with repair)
- only for follow-ups in the interactive chat (the last `[rag].history_turns` exchanges); a failure falls back to the
  follow-up as it is