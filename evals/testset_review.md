# Testset review

A person checks `evals/testset.json` against the documents. For every case:
1. the question is natural (an employee would ask it this way);
2. the **reference** is correct and complete according to the source below;
3. the **must** facts are really what makes an answer right or wrong;
4. the **source** is the right document and section (the chunk text is shown);
5. for `no_answer`: no document answers it.

Write in the **Verdict** line: `OK` or `FIX: <what to change>`.

## q01 · paraphrase · groups: all_employees

**Question:** How many days a week can I work from home?

**Reference:** One day a week (Wednesday or Thursday) with 0-3 years of service, two days a week after 3 years.

**Must (key facts, one option per group):** one day / 1 day · two days / 2 days

**Source quote:** "0 – 3 years of service – one day per week" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 2 - Operational Policies > 2-5. Remote Work/Telecommuting > Introduction*
>
> #### 2-5. Remote Work/Telecommuting
>
> ###### Introduction
>
> The It-product Remote Work policy is designed to offer flexibility and work-life balance to our team. As part of this policy, we are implementing a seniority-based approach for granting additional remote days, which aims to reward your dedication and commitment to the company.
>
> Employees are eligible to work remotely as follows:
>
> - 0 – 3 years of service – one day per week (Wednesday or Thursday)
> - 3+ years of service – two days per week (Tuesday, Wednesday or Thursday)

**Verdict:** 

---

## q02 · outdated version (trap) · groups: all_employees, hr

**Question:** How much does the company pay toward my commute if I come to the office three days a week?

**Reference:** $75 per month for employees who come to the office 2-3 days a week.

**Must (key facts, one option per group):** $75 / 75

**Trap (not shown to the judge):** The archived 2025 handbooks (hr only) still give a flat $132 a month; an answer with $132 relies on an outdated source.

**Source quote:** "Employees commuting 2–3 days per week: $75 per month" → 2 chunk(s)

> *Commuter Benefits Policy 5.1.26.docx — Commuter Benefits Policy > Employer Contributions*
>
> ## Employer Contributions
>
> It-product provides monthly commuter benefit contributions based on an employee’s in-office work schedule:
>
> - Employees commuting 2–3 days per week: $75 per month
> - Employees commuting 4–5 days per week: $132 per month
>
> Employees participating in the program must elect to apply employer contributions to either transit benefits or parking benefits. Employer contributions will be added to employee accounts at the end of each month.
>
> Employer contribution amounts are subject to applicable IRS limits, which may change annually.

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 3 - Benefits > New York City Safe and Sick Leave (Includes The New York Paid Sick Leave Law) > 3-16. Commuter Benefit Program > Employer Contributions*
>
> ###### Employer Contributions
>
> It-product provides monthly commuter benefit contributions based on an employee’s in-office work schedule:
>
> - Employees commuting 2–3 days per week: $75 per month
> - Employees commuting 4–5 days per week: $132 per month
>
> Employees participating in the program must elect to apply employer contributions to either transit benefits or parking benefits. Employer contributions will be added to employee accounts at the end of each month.
>
> Employer contribution amounts are subject to applicable IRS limits, which may change annually.

**Verdict:** 

---

## q03 · paraphrase · groups: all_employees

**Question:** How long is the probation period for a new hire?

**Reference:** 3 months; 1 month for Affordable Housing and Property Tax Analysts.

**Must (key facts, one option per group):** 3 months / three months

**Source quote:** "standard adaptation (probation) period is 3 months" → 2 chunk(s)

> *HR-Onboarding and Adaptation Process-071126-120547.pdf — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> All new employees must sign an employment contract prior to their official start date (via Vchasno). The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month). During the adaptation period, feedback must be provided at least twice:
> mid-point feedback,
> final feedback at the end of the period. Feedback is provided by the Direct Manager during online 1:1 meetings. The Manager is responsible for the final adaptation decision.

> *Onboarding Process EU_EN.docx — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> - All new employees must sign an employment contract prior to their official start date (via Vchasno).
> - The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month).
> - During the adaptation period, feedback must be provided at least twice:
>   - mid-point feedback,
>   - final feedback at the end of the period.
> - Feedback is provided by the Direct Manager during online 1:1 meetings.
> - The Manager is responsible for the final adaptation decision.

**Verdict:** 

---

## q04 · paraphrase · groups: all_employees

**Question:** What should the background of my profile picture look like?

**Reference:** A solid neutral background, gray is preferred.

**Must (key facts, one option per group):** neutral

**Source quote:** "solid neutral background" → 1 chunk(s)

> *HR-Bamboo Profile Photo Requirements-071126-120706.pdf — Bamboo Profile Photo Requirements > Photo Requirements*
>
> ## Photo Requirements
>
> Each employee is required to upload a professional headshot that meets the following criteria and use the same photo across all internal platforms.
> The photo must:
> Be recent and high quality
> Have a solid neutral background (gray is preferred)
> Include only the employee (no other people, logos, or additional objects) Be in a square format (1:1 ratio) and properly centered

**Verdict:** 

---

## q05 · paraphrase · groups: all_employees

**Question:** What time does the Costa Rica team start and finish the workday?

**Reference:** 7:00 am to 4:00 pm Costa Rica time, with a 1-hour lunch break.

**Must (key facts, one option per group):** 7.00 am / 7:00 / 7 am · 4.00 pm / 4:00 / 4 pm

**Source quote:** "7.00 am – 4.00 pm Costa Rica Time" → 1 chunk(s)

> *Costa Rica Team Manual.pdf — – Team Member Manual for Costa Rica Team*
>
> Working Hours
> The standard working hours for Costa Rica team are:
> 7.00 am – 4.00 pm Costa Rica Time with 1 hour lunch break. Contractors will be assigned a work schedule and will be expected to begin and end work according to the schedule. To accommodate the needs of the business, at some point may need to change individual work schedules on either a short-term or long-term basis Time Off Policies
> - Paid Time Off
> Contractors are entitled to 12 paid days off per year. These days should be used for vacation, personal time, or any other reason.

**Verdict:** 

---

## q06 · paraphrase · groups: all_employees

**Question:** On which days are the advanced English classes held?

**Reference:** The C1-C2 group meets on Monday and Wednesday, 10:00-11:00 Kyiv time.

**Must (key facts, one option per group):** monday · wednesday

**Source quote:** "C1–C2 Group: Monday & Wednesday" → 1 chunk(s)

> *HR-English Language Program Policy-071126-120805.pdf — English Language Program Policy > Program Overview*
>
> ## Program Overview
>
> The company provides structured group English lessons based on proficiency level.
> Current schedule (Kyiv time — EET/EEST depending on season):
> Daily sessions: 10:00–11:00 AM (Kyiv time)
> C1–C2 Group: Monday & Wednesday
> B2+ Group: Tuesday & Thursday
> Speaking Club: Friday
> Schedules may be adjusted based on participation and business needs.

**Verdict:** 

---

## q07 · paraphrase · groups: all_employees

**Question:** What rate am I paid for hours beyond 40 in a week?

**Reference:** Non-exempt employees get 1.5 times their normal hourly wage for hours over 40 in a workweek.

**Must (key facts, one option per group):** 1.5 / one and one-half / time and a half

**Source quote:** "one and one-half times (1.5) their normal hourly wage" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 2 - Operational Policies > 2-6. Overtime*
>
> #### 2-6. Overtime
>
> Like most companies in our industry, It-product experiences periods of extremely high activity. During these busy periods, additional work is required from all of us. Supervisors are responsible for monitoring business activity and requesting overtime work if necessary. Effort will be made to provide employees with adequate advance notice in such situations.
>
> Any non-exempt employee who works overtime will be compensated at the rate of one and one-half times (1.5) their normal hourly wage for all time worked in excess of 40 hours each week, unless otherwise required by law.

**Verdict:** 

---

## q08 · paraphrase · groups: all_employees

**Question:** How many hours of paid sick time do I get each year in New York?

**Reference:** 40 hours of paid safe and sick time, granted at the start of each calendar year.

**Must (key facts, one option per group):** 40 hours

**Source quote:** "grant of 40 hours of paid safe and sick time" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 3 - Benefits > 3-4. New York City Safe and Sick Leave (Includes the New York Paid Sick Leave Law) > Grant*
>
> ###### Grant
>
> Employees receive a grant of 40 hours of paid safe and sick time at the start of employment. Thereafter, at the start of each calendar year, employees receive a grant of 40 hours of safe and sick time for the year. For purposes of this policy, the calendar year is January 1 through December 31.

**Verdict:** 

---

## q09 · paraphrase · groups: all_employees

**Question:** How often is pay reviewed for the Affordable Housing Processing Team?

**Reference:** Every 6 months; the hiring manager tracks the cycle and starts the review.

**Must (key facts, one option per group):** 6 months / six months

**Source quote:** "salary reviews are conducted every 6 months" → 1 chunk(s)

> *HR-Salary Review Process via BambooHR_ A Structured Overview-071126-121239.pdf — Salary Review Process via BambooHR: A Structured Overview > 7. Specific Requirement: Affordable Housing Processing Team*
>
> ## 7. Specific Requirement: Affordable Housing Processing Team
>
> a. For employees in the Affordable Housing Processing Team, salary reviews are conducted every 6 months.
> b. The Hiring Manager is responsible for:
> - tracking each employeeʼs 6-month review cycle;
> - initiating salary review requests on time;
> - ensuring no reviews are missed.
> c. All reviews must be processed through BambooHR, following the standard process described above.

**Verdict:** 

---

## q10 · paraphrase · groups: all_employees

**Question:** How many floating holidays do employees on the EU team get?

**Reference:** Five floating holidays per calendar year.

**Must (key facts, one option per group):** five / 5

**Source quote:** "entitled to five (5) Floating Holidays" → 1 chunk(s)

> *HR-Paid Holidays & Floating Holidays Policy-071126-120838.pdf — Paid Holidays & Floating Holidays Policy > Floating Holidays (EU Team)*
>
> ## Floating Holidays (EU Team)
>
> In addition to Company-observed U.S. holidays, employees in the EU Team are entitled to five (5) Floating Holidays per calendar year. Floating Holidays are designated exclusively for observing official Ukrainian public holidays and may not be used as general-purpose paid time off, except as provided in the “Additional Use for Emergencies and Safety Situations” section below.

**Verdict:** 

---

## q11 · paraphrase · groups: all_employees

**Question:** How much vacation do US employees accrue per year during their first three years?

**Reference:** 1.77 hours a week, 92 hours (11.5 days) a year for full-time employees.

**Must (key facts, one option per group):** 92 hours / 11.5 days

**Source quote:** "| 0–3 years | 1.77 hours | 92 hours (11.5 days) |" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 3 - Benefits > 3-3. Paid Vacations*
>
> | Length of Service | Weekly Accrual | Annual Equivalent |
> | --- | --- | --- |
> | 0–3 years | 1.77 hours | 92 hours (11.5 days) |
> | 3–5 years | 2.62 hours | 136 hours (17 days) |
> | 5+ years | 3.38 hours | 176 hours (22 days) |
> | *Part-time employees | 0.77 hours | 40 hours |

**Verdict:** 

---

## q12 · paraphrase · groups: all_employees

**Question:** How many days of annual leave do employees in Ukraine have?

**Reference:** 24 calendar days of paid annual leave a year.

**Must (key facts, one option per group):** 24 / twenty-four

**Source quote:** "twenty-four (24) calendar days of paid annual leave" → 1 chunk(s)

> *HR-Paid Vacation-071126-120916.pdf — Paid Vacation > Vacation Entitlement*
>
> # Paid Vacation
>
> ## Vacation Entitlement
>
> Employees are eligible for twenty-four (24) calendar days of paid annual leave in accordance with Ukrainian labor legislation.
> Vacation accrues proportionally throughout the calendar year and is calculated daily based on the employee's continuous employment.
> BambooHR is the Company's official system of record for vacation accrual and balances. The vacation balance displayed in BambooHR reflects the employee's earned (accrued) vacation entitlement.

**Verdict:** 

---

## q13 · exact term · groups: all_employees

**Question:** DB-450

**Reference:** DB-450 is the short-term disability claim form: get it from HR and send it to NYSIF Disability Benefits Claims.

**Must (key facts, one option per group):** disability

**Source quote:** "Short-term disability claim form (DB-450)" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 3 - Benefits > New York City Safe and Sick Leave (Includes The New York Paid Sick Leave Law) > 3-15. Statutory Short-Term Disability Benefits*
>
> Short-term disability claim form (DB-450) can be obtained by contacting Human Resources. Completed DB-450 form should be sent to: NYSIF Disability Benefits Claims; 15 Computer Drive West; Albany, NY12205. Medical evidence regarding your disability may be required for the entire period you are requesting benefits.
>
> Disability benefits will pay 50% of your average wages (calculated over the prior eight weeks) up to a maximum of $170 per week.

**Source quote:** "DB-450" → 1 chunk(s)

> *It-product HR Procedures Manual.docx — It-product HR Procedures Manual > Payroll Checklist*
>
> 8. Paid Family Leave/Short-Term Disability Leave
> - Insurance carrier – NYSIF (https://identity.nysif.com/login/ )
> - STD – 4 weeks pre-natal leave/6 weeks after birth (8 weeks after C-section) (50% income replacement)
> - (Form: file:///C:/Users/elena/Downloads/2024_WCB_DB-450.pdf )
> - PFL – 12 weeks for baby bonding (67% income replacement)

**Verdict:** 

---

## q14 · exact term · groups: all_employees

**Question:** form PFL-DC-120

**Reference:** PFL-DC-120 is the Paid Family Leave Discrimination Complaint filed with the Workers' Compensation Board.

**Must (key facts, one option per group):** discrimination

**Source quote:** "PFL-DC-120" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 4 - Leaves Of Absence > 4-2. State Paid Family Leave > Questions and/or Complaints About PFL*
>
> If the Company does not comply with the employee's request for reinstatement within 30 days, the employee may file a PFL discrimination complaint with the Workers ‘Compensation Board using the Paid Family Leave Discrimination Complaint (Form PFL-DC-120), which is also available on the New York PFL website. Once the employee's complaint is received, the Board will assemble the employee's case and schedule a preliminary hearing in front of a workers' compensation law judge.

**Verdict:** 

---

## q15 · exact term · groups: all_employees

**Question:** Vchasno

**Reference:** New employees sign the employment contract in Vchasno before their official start date.

**Must (key facts, one option per group):** contract

**Source quote:** "employment contract prior to their official start date (via Vchasno)" → 2 chunk(s)

> *HR-Onboarding and Adaptation Process-071126-120547.pdf — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> All new employees must sign an employment contract prior to their official start date (via Vchasno). The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month). During the adaptation period, feedback must be provided at least twice:
> mid-point feedback,
> final feedback at the end of the period. Feedback is provided by the Direct Manager during online 1:1 meetings. The Manager is responsible for the final adaptation decision.

> *Onboarding Process EU_EN.docx — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> - All new employees must sign an employment contract prior to their official start date (via Vchasno).
> - The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month).
> - During the adaptation period, feedback must be provided at least twice:
>   - mid-point feedback,
>   - final feedback at the end of the period.
> - Feedback is provided by the Direct Manager during online 1:1 meetings.
> - The Manager is responsible for the final adaptation decision.

**Verdict:** 

---

## q16 · exact term · groups: all_employees

**Question:** Speaking Club

**Reference:** The English Speaking Club meets on Fridays, 10:00-11:00 Kyiv time.

**Must (key facts, one option per group):** friday

**Source quote:** "Speaking Club: Friday" → 1 chunk(s)

> *HR-English Language Program Policy-071126-120805.pdf — English Language Program Policy > Program Overview*
>
> ## Program Overview
>
> The company provides structured group English lessons based on proficiency level.
> Current schedule (Kyiv time — EET/EEST depending on season):
> Daily sessions: 10:00–11:00 AM (Kyiv time)
> C1–C2 Group: Monday & Wednesday
> B2+ Group: Tuesday & Thursday
> Speaking Club: Friday
> Schedules may be adjusted based on participation and business needs.

**Verdict:** 

---

## q17 · question in another language · groups: all_employees

**Question:** Скільки днів на тиждень можна працювати з дому?

**Reference:** Один день на тиждень при стажі до 3 років, два дні після 3 років.

**Must (key facts, one option per group):** one day / 1 day / один день / 1 день · two days / 2 days / два дні / 2 дні

**Source quote:** "0 – 3 years of service – one day per week" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 2 - Operational Policies > 2-5. Remote Work/Telecommuting > Introduction*
>
> #### 2-5. Remote Work/Telecommuting
>
> ###### Introduction
>
> The It-product Remote Work policy is designed to offer flexibility and work-life balance to our team. As part of this policy, we are implementing a seniority-based approach for granting additional remote days, which aims to reward your dedication and commitment to the company.
>
> Employees are eligible to work remotely as follows:
>
> - 0 – 3 years of service – one day per week (Wednesday or Thursday)
> - 3+ years of service – two days per week (Tuesday, Wednesday or Thursday)

**Verdict:** 

---

## q18 · question in another language · groups: all_employees

**Question:** Скільки днів щорічної відпустки мають працівники в Україні?

**Reference:** 24 календарні дні оплачуваної щорічної відпустки.

**Must (key facts, one option per group):** 24 / twenty-four / двадцять чотири

**Source quote:** "twenty-four (24) calendar days of paid annual leave" → 1 chunk(s)

> *HR-Paid Vacation-071126-120916.pdf — Paid Vacation > Vacation Entitlement*
>
> # Paid Vacation
>
> ## Vacation Entitlement
>
> Employees are eligible for twenty-four (24) calendar days of paid annual leave in accordance with Ukrainian labor legislation.
> Vacation accrues proportionally throughout the calendar year and is calculated daily based on the employee's continuous employment.
> BambooHR is the Company's official system of record for vacation accrual and balances. The vacation balance displayed in BambooHR reflects the employee's earned (accrued) vacation entitlement.

**Verdict:** 

---

## q19 · question in another language · groups: all_employees

**Question:** Який фон має бути на фото профілю?

**Reference:** Однотонний нейтральний фон, бажано сірий.

**Must (key facts, one option per group):** neutral / нейтральн

**Source quote:** "solid neutral background" → 1 chunk(s)

> *HR-Bamboo Profile Photo Requirements-071126-120706.pdf — Bamboo Profile Photo Requirements > Photo Requirements*
>
> ## Photo Requirements
>
> Each employee is required to upload a professional headshot that meets the following criteria and use the same photo across all internal platforms.
> The photo must:
> Be recent and high quality
> Have a solid neutral background (gray is preferred)
> Include only the employee (no other people, logos, or additional objects) Be in a square format (1:1 ratio) and properly centered

**Verdict:** 

---

## q20 · question in another language · groups: all_employees

**Question:** Скільки триває випробувальний термін для нового працівника?

**Reference:** 3 місяці; для Affordable Housing і Property Tax Analysts — 1 місяць.

**Must (key facts, one option per group):** 3 months / three months / 3 місяці / три місяці

**Source quote:** "standard adaptation (probation) period is 3 months" → 2 chunk(s)

> *HR-Onboarding and Adaptation Process-071126-120547.pdf — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> All new employees must sign an employment contract prior to their official start date (via Vchasno). The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month). During the adaptation period, feedback must be provided at least twice:
> mid-point feedback,
> final feedback at the end of the period. Feedback is provided by the Direct Manager during online 1:1 meetings. The Manager is responsible for the final adaptation decision.

> *Onboarding Process EU_EN.docx — Onboarding and Adaptation Process > General Provisions*
>
> ## General Provisions
>
> - All new employees must sign an employment contract prior to their official start date (via Vchasno).
> - The standard adaptation (probation) period is 3 months (for Affordable Housing and Property Tax Analysts, the adaptation period is 1 month).
> - During the adaptation period, feedback must be provided at least twice:
>   - mid-point feedback,
>   - final feedback at the end of the period.
> - Feedback is provided by the Direct Manager during online 1:1 meetings.
> - The Manager is responsible for the final adaptation decision.

**Verdict:** 

---

## q21 · hr-only document · groups: all_employees, hr

**Question:** With how many days' notice can either party terminate a contractor agreement?

**Reference:** Either party may terminate for any reason with 7 days' prior written notice.

**Must (key facts, one option per group):** 7 (seven) days / 7 days / seven days

**Source quote:** "terminate this Agreement for any reason upon 7 (seven) days' prior written notice" → 1 chunk(s)

> *Contractor Agreement (Costa Rica).docx — CONSULTING AND CONFIDENTIAL SERVICES AGREEMENT > 10. Termination of Agreement*
>
> ## 10. Termination of Agreement
>
> Each party shall have the right to terminate this Agreement by written notice to the other if a party has materially breached any obligation herein and such breach remains uncured for a period of 30 days after written notice of such breach is sent to the other party.
>
> Each party shall have the right to terminate this Agreement for any reason upon 7 (seven) days' prior written notice to the other party. Upon such termination, all amounts owed to Consultant under this Agreement for accepted work shall immediately become due.

**Verdict:** 

---

## q22 · hr-only document · groups: all_employees, hr

**Question:** Do we offer company benefits to interns?

**Reference:** No. A temporary intern is not eligible for Company benefits; interns are paid hourly, weekly, and are eligible for overtime.

**Must (key facts, one option per group):** not be eligible / not eligible / no benefits / not entitled

**Source quote:** "As a temporary intern, you will not be eligible for Company benefits." → 1 chunk(s)

> *Offer Letter Template - Intern.docx — ADDRESS*
>
> In consideration of your services, you will be paid $[HOURLY RATE] per hour, paid weekly and subject to all required withholdings and deductions. This is a part-time, non-exempt position, and as such, you will be eligible for overtime pay in accordance with applicable law. You are expected to work approximately [XX] hours per week, with scheduling coordinated based on team needs and your availability. As a temporary intern, you will not be eligible for Company benefits.

**Verdict:** 

---

## q23 · outdated version (trap) · groups: all_employees, hr

**Question:** I joined three months ago. Can I already work from home?

**Reference:** Yes. New employees may work remotely after 60 days of employment, and with 0-3 years of service that is one day a week (Wednesday or Thursday).

**Must (key facts, one option per group):** one day / 1 day

**Trap (not shown to the judge):** The archived handbooks (hr only) list weekly remote days from 1-3 years of service, so an answer built on them says 'not before 1 year'; they also say 60 days, so they contradict themselves.

**Source quote:** "0 – 3 years of service – one day per week" → 1 chunk(s)

> *It-product Handbook (US) 2026.docx — Employee Handbook > Section 2 - Operational Policies > 2-5. Remote Work/Telecommuting > Introduction*
>
> #### 2-5. Remote Work/Telecommuting
>
> ###### Introduction
>
> The It-product Remote Work policy is designed to offer flexibility and work-life balance to our team. As part of this policy, we are implementing a seniority-based approach for granting additional remote days, which aims to reward your dedication and commitment to the company.
>
> Employees are eligible to work remotely as follows:
>
> - 0 – 3 years of service – one day per week (Wednesday or Thursday)
> - 3+ years of service – two days per week (Tuesday, Wednesday or Thursday)

**Verdict:** 

---

## q24 · no answer in the documents · groups: all_employees

**Question:** Does the company reimburse a gym membership?

**Reference:** The documents do not say: the bot must say it has no information.

*No source: the documents should not answer this. Check that no document does.*

**Verdict:** 

---

## q25 · no answer in the documents · groups: all_employees

**Question:** Do I get a 13th-month salary?

**Reference:** The documents do not say: the bot must say it has no information.

*No source: the documents should not answer this. Check that no document does.*

**Verdict:** 

---

## q26 · no answer in the documents · groups: all_employees

**Question:** Чи можна приводити собаку в офіс?

**Reference:** Документи цього не описують: бот має сказати, що не має такої інформації.

*No source: the documents should not answer this. Check that no document does.*

**Verdict:** 

---
