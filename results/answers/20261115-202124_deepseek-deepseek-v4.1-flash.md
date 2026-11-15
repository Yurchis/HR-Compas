# Answer eval: deepseek/deepseek-v4.1-flash, prompt v6_rag_cited

26 cases, $0.0131.

| metric | value |
|---|---|
| pass | 0.85 |
| facts | 0.87 |
| cited | 0.83 |
| attributed | 1.00 |
| abstain | 1.00 |
| false_abstain | 0.13 |
| judge | 0.85 |
| grounded | 1.00 |

## By kind

| kind | pass |
|---|---|
| access | 1.00 |
| cross-lingual | 0.50 |
| exact | 0.75 |
| no_answer | 1.00 |
| paraphrase | 1.00 |
| stale | 0.50 |

## Cases to read

### q01 (paraphrase): How many days a week can I work from home?

- answer: Employees with 0 – 3 years of service may work remotely one day per week (Wednesday or Thursday), while those with 3+ years of service may work remotely two days per week (Tuesday, Wednesday or Thursday) [1].
- reference: One day a week (Wednesday or Thursday) with 0-3 years of service, two days a week after 3 years.
- deterministic: facts True, cited True, abstain None
- judge: incorrect. The key fact compared is the number of days employees can work from home based on their years of service. The answer correctly states that employees with 0-3 years can work one day a week and those with over 3 years can work two days a week, but it incorrectly specifies the days for those with 3+ years of service.

### q13 (exact): DB-450

- answer: I only answer questions about working at the company. Please contact HR with this one.
- reference: DB-450 is the short-term disability claim form: get it from HR and send it to NYSIF Disability Benefits Claims.
- deterministic: facts False, cited False, abstain None
- judge: incorrect. The key fact is that DB-450 is the short-term disability claim form, which the assistant did not provide. Instead, the assistant redirected the question to HR without answering it.

### q17 (cross-lingual): Скільки днів на тиждень можна працювати з дому?

- answer: У наявних джерелах немає інформації про те, скільки днів на тиждень можна працювати з дому. Будь ласка, зверніться до HR із цим питанням.
- reference: Один день на тиждень при стажі до 3 років, два дні після 3 років.
- deterministic: facts False, cited False, abstain None
- judge: incorrect. The key fact is the number of days one can work from home, which is specified as one day for less than 3 years of experience and two days for more than 3 years. The answer incorrectly states that this information is not available.

### q19 (cross-lingual): Який фон має бути на фото профілю?

- answer: У мене немає цієї інформації. Будь ласка, зверніться до HR.
- reference: Однотонний нейтральний фон, бажано сірий.
- deterministic: facts False, cited False, abstain None
- judge: incorrect. The key fact is the requirement for a neutral solid background, preferably gray, which the assistant did not provide.

### q23 (stale): I joined three months ago. Can I already work from home?

- answer: No — under the remote work policy, eligibility starts at 1 year of service: 1–3 years of service gives one day per week (Wednesday or Thursday), and 3+ years gives two days per week (Tuesday, Wednesday or Thursday) [1]. With three months of service you do not yet meet the minimum, and the extra remote days also require more than 1 year of service [1].
- reference: Yes, one day a week (Wednesday or Thursday); the archived 2025 handbook started remote days only after 1 year.
- deterministic: facts True, cited False, abstain None
- judge: correct. The key fact is that eligibility for remote work starts after 1 year of service, which the reference confirms. The answer correctly states that with three months of service, the individual does not meet the minimum requirement to work from home.
