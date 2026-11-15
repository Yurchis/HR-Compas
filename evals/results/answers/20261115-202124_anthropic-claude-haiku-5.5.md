# Answer eval: anthropic/claude-haiku-5.5, prompt v6_rag_cited

26 cases, $0.0155.

| metric | value |
|---|---|
| pass | 0.88 |
| facts | 0.91 |
| cited | 0.87 |
| attributed | 0.71 |
| abstain | 1.00 |
| false_abstain | 0.09 |
| judge | 0.81 |
| grounded | 0.67 |

## By kind

| kind | pass |
|---|---|
| access | 1.00 |
| cross-lingual | 0.50 |
| exact | 1.00 |
| no_answer | 1.00 |
| paraphrase | 1.00 |
| stale | 0.50 |

## Cases to read

### q01 (paraphrase): How many days a week can I work from home?

- answer: Employees with 0 – 3 years of service can work remotely one day per week (Wednesday or Thursday) [1]. Employees with 3+ years of service can work remotely two days per week (Tuesday, Wednesday or Thursday) [1].
- reference: One day a week (Wednesday or Thursday) with 0-3 years of service, two days a week after 3 years.
- deterministic: facts True, cited True, abstain None
- judge: incorrect. The key fact compared is the number of days employees can work from home based on their years of service. The answer correctly states that employees with 0-3 years can work one day a week and those with over 3 years can work two days a week, but it incorrectly specifies the days for employees with more than 3 years of service.

### q03 (paraphrase): How long is the probation period for a new hire?

- answer: The standard adaptation (probation) period for new hires is 3 months [1, 2]. For Affordable Housing and Property Tax Analysts, it is 1 month [1, 2]. These rules are listed for Ukraine (UA) [1, 2].
- reference: 3 months; 1 month for Affordable Housing and Property Tax Analysts.
- deterministic: facts True, cited True, abstain None
- judge: correct. The answer correctly states that the probation period for new hires is 3 months and specifies that it is 1 month for Affordable Housing and Property Tax Analysts, matching the reference.
- not in the cited sources: These rules are listed for Ukraine (UA)

### q08 (paraphrase): How many hours of paid sick time do I get each year in New York?

- answer: Employees receive a grant of 40 hours of safe and sick time at the start of each calendar year [1]. Employees may not use more than 40 hours of safe and sick time in any calendar year [2]. Unused time may be carried over to the following year, but usage is still capped at 40 hours per year [3].
- reference: 40 hours of paid safe and sick time, granted at the start of each calendar year.
- deterministic: facts True, cited True, abstain None
- judge: correct. The key fact is the number of hours of paid sick time, which is 40 hours per year. Both the reference and the answer correctly state this fact.
- not in the cited sources: Employees receive a grant of 40 hours of safe and sick time at the start of each calendar year

### q11 (paraphrase): How much vacation do US employees accrue per year during their first three years?

- answer: US employees in their first three years are shown two different amounts. The policy update effective 2026-01-01 gives 1.77 hours weekly, which is 11.5 days per year [1]. The same-dated update gives 80 hours (10 days) per year [2]. The older handbook lists 92 hours (11.5 days) per year [3]. Please confirm the correct figure with HR.
- reference: 1.77 hours a week, 92 hours (11.5 days) a year for full-time employees.
- deterministic: facts True, cited True, abstain None
- judge: incorrect. The key fact is the amount of vacation US employees accrue per year during their first three years, which is stated as 92 hours (11.5 days) in the reference. The answer provides multiple figures and suggests confirming with HR, which does not directly answer the question.
- not in the cited sources: Please confirm the correct figure with HR.

### q13 (exact): DB-450

- answer: DB-450 is the short-term disability claim form, which you can get from Human Resources. Send the completed form to NYSIF Disability Benefits Claims, 15 Computer Drive West, Albany, NY12205 [1]. The payroll checklist also links to this form under short-term disability leave [2].
- reference: DB-450 is the short-term disability claim form: get it from HR and send it to NYSIF Disability Benefits Claims.
- deterministic: facts True, cited True, abstain None
- judge: correct. The key fact is that DB-450 is the short-term disability claim form, which both the reference and the answer correctly state. The answer provides additional details but does not contradict the reference.
- not in the cited sources: The payroll checklist links to this form under short-term disability leave

### q17 (cross-lingual): Скільки днів на тиждень можна працювати з дому?

- answer: У мене немає цієї інформації: джерела не вказують, скільки днів на тиждень можна працювати з дому. Будь ласка, запитайте про це HR.
- reference: Один день на тиждень при стажі до 3 років, два дні після 3 років.
- deterministic: facts False, cited False, abstain None
- judge: incorrect. The key fact is the number of days one can work from home, which is specified as 'один день на тиждень при стажі до 3 років, два дні після 3 років' in the reference. The assistant's answer does not provide this information.

### q19 (cross-lingual): Який фон має бути на фото профілю?

- answer: На жаль, у мене немає цієї інформації в джерелах. Будь ласка, зверніться до HR за відповіддю на питання про фон фото профілю.
- reference: Однотонний нейтральний фон, бажано сірий.
- deterministic: facts False, cited False, abstain None
- judge: incorrect. The key fact is that the profile photo should have a solid neutral background, preferably gray. The assistant's answer states that they do not have this information, which is incorrect since the reference provides a clear answer.

### q21 (access): With how many days' notice can either party terminate a contractor agreement?

- answer: Either party can terminate the consulting agreement for any reason with 7 (seven) days' prior written notice to the other party [1]. This is the Costa Rica consulting agreement clause, so it may not apply to agreements in other countries.
- reference: Either party may terminate for any reason with 7 days' prior written notice.
- deterministic: facts True, cited True, abstain None
- judge: correct. The key fact compared is the notice period for terminating the contractor agreement, which is 7 days. Both the reference and the answer correctly state this notice period.
- not in the cited sources: This is the Costa Rica consulting agreement clause; It may not apply to agreements in other countries

### q22 (access): Do we offer company benefits to interns?

- answer: No, temporary interns are not eligible for Company benefits [1]. This is stated in the USA intern letter, so other countries may differ [1].
- reference: No. A temporary intern is not eligible for Company benefits; interns are paid hourly, weekly, and are eligible for overtime.
- deterministic: facts True, cited True, abstain None
- judge: correct. The key fact is that temporary interns are not eligible for Company benefits, which is correctly stated in both the reference and the answer. The additional detail about other countries differing does not contradict the reference.
- not in the cited sources: other countries may differ

### q23 (stale): I joined three months ago. Can I already work from home?

- answer: The USA Employee Handbook sets remote-work days only for employees with at least 1 year of service, starting with 1 day per week for 1–3 years [1]. It says nothing about employees with under 1 year, so based on these sources you are not shown as eligible yet [1]. This rule applies to USA employees only, so please ask HR to confirm for your location.
- reference: Yes, one day a week (Wednesday or Thursday); the archived 2025 handbook started remote days only after 1 year.
- deterministic: facts True, cited False, abstain None
- judge: incorrect. The key fact is whether the employee can work from home after three months. The reference states that remote work days are allowed after 1 year, while the answer incorrectly implies that the employee is not eligible yet, which contradicts the reference's information about the specific allowance for one day a week after three months.
- not in the cited sources: You should ask HR to confirm for your location.
