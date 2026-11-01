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

## intake v1 — `intake_promt.md` (2026-10-27)
**Hypothesis:** a separate cheap call that determines the language, the topic and the employee profile makes it possible not to run off-topic questions through the handbook (~30k tokens) and to narrow the context by country/sub-company.
- output — JSON by `hr_compass/intake.py` (`language`, `in_scope`, `country`, `sub_company`, `needs_clarification`, `clarifying_question`)
- country/sub-company are filled only if named explicitly; a clarification — only when without it the answer would be wrong
- does not change the answer prompts v1/v2

## intake v2 — `intake_v2_en.md` (2026-10-31)
**Hypothesis:** models follow instructions in English more precisely and with fewer tokens than in Ukrainian.
- a literal English translation of intake v1; fields, values and rules unchanged
- `chat.py` uses v2 by default; v1 is available via `--intake-prompt prompts/intake_promt.md`
- expected effect: the same classification, fewer tokens per call
