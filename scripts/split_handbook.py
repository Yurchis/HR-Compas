"""Split an office handbook PDF into knowledge chunks (data/raw/*.json, see data/handbook.schema.json).

The section layout (ids, titles, metadata in META) is the one of the Ukraine-office handbook
(`data/Handbook - Ukraine.pdf`: sections 1-1..3-5 + closing words). A handbook with another table of
contents needs its own META.

    python scripts/split_handbook.py "data/Handbook - Ukraine.pdf" --country UA --sub-company IT-Product
    python scripts/split_handbook.py "data/Handbook - Costa Rica.pdf" --country "Costa Rica" --sub-company IT-Outsourcing
    python scripts/split_handbook.py "data/Handbook - Ukraine.pdf" --country UA --sub-company IT-Product --dry-run

For a country other than UA, "Ukraine"/"Ukrainian" in the text is replaced with that country (COUNTRY_WORDS):
the Costa Rica set is built from the Ukraine handbook and its chunks are edited by hand afterwards, so existing
files are never overwritten without --force.

Requires `pypdf` (requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COUNTRIES = {"USA": "us", "UA": "ua", "Costa Rica": "cr"}  # schema enum -> file prefix
# Country / adjective as written in the text. The source PDF is the Ukraine one, so for another --country
# these words are swapped (Costa Rica: a placeholder set built from the Ukraine handbook, edited by hand later).
COUNTRY_WORDS = {"USA": ("United States", "US"), "UA": ("Ukraine", "Ukrainian"), "Costa Rica": ("Costa Rica", "Costa Rican")}
SOURCE_COUNTRY = "UA"
SUB_COMPANIES = ("IT-Outsourcing", "IT-Product")

SECTIONS = {1: "Governing Principles Of Employment", 2: "Operation Policies", 3: "Benefits"}

# id, title, file slug, category, applies_to, paid_status, eligibility (who, min_tenure) or None
META = [
    ("1-1", "Introduction", "introduction", "company", ["all"], "not_applicable", None),
    ("1-2", "It Company Vision Statement", "it_company_vision_statement", "company", ["all"], "not_applicable", None),
    ("1-3", "Values and Principles", "values_and_principles", "company", ["all"], "not_applicable", None),
    ("1-4", "Equal Employment Opportunity", "equal_employment_opportunity", "anti_discrimination", ["all"], "not_applicable", None),
    ("1-5", "Non-Harassment", "non_harassment", "anti_discrimination", ["all"], "not_applicable", None),
    ("1-6", "Workplace Violence", "workplace_violence", "health_safety", ["all"], "not_applicable", None),
    ("2-1", "Employee Classifications", "employee_classifications", "employment", ["all"], "not_applicable", None),
    ("2-2", "Working Hours and Schedule", "working_hours_and_schedule", "schedule", ["all"], "not_applicable", None),
    ("2-3", "Remote Work/Telecommuting", "remote_work_telecommuting", "schedule", ["all"], "not_applicable",
     ("Employees whose job duties and work performance are approved for remote work (case-by-case)", None)),
    ("2-4", "Your Paycheck", "your_paycheck", "pay", ["all"], "not_applicable", None),
    ("2-5", "Performance Review", "performance_review", "employment", ["all"], "not_applicable", None),
    ("2-6", "Workplace Conduct", "workplace_conduct", "conduct", ["all"], "not_applicable", None),
    ("2-7", "Attendance and Punctuality", "attendance_and_punctuality", "conduct", ["all"], "not_applicable", None),
    ("2-8", "Drug-Free Workplace", "drug_free_workplace", "health_safety", ["all"], "not_applicable", None),
    ("2-9", "Use of Communications and Computer Systems", "use_of_communications_and_computer_systems", "conduct",
     ["all"], "not_applicable", None),
    ("2-10", "Confidential Company Information", "confidential_company_information", "conduct", ["all"], "not_applicable", None),
    ("2-11", "Conflict of Interest and Business Ethics", "conflict_of_interest_and_business_ethics", "conduct",
     ["all"], "not_applicable", None),
    ("2-12", "Use of Facilities, Equipment and Property, including Intellectual Property",
     "use_of_facilities_equipment_and_property_including", "conduct", ["all"], "not_applicable", None),
    ("2-13", "Health and Safety", "health_safety", "health_safety", ["all"], "not_applicable", None),
    ("3-1", "Paid Holidays", "paid_holidays", "time_off", ["all"], "paid",
     ("All employees: 6 US holidays plus 5 floating days for Ukrainian public holidays; no more than 1 paid holiday "
      "per 30 days; 4 days' notice", None)),
    ("3-2", "Paid Vacation", "paid_vacation", "time_off", ["all"], "paid",
     ("All employees: 24 calendar days a year after 6 months of continuous employment, pro-rated before that; "
      "some categories get the full leave earlier",
      {"value": 26, "unit": "weeks"})),  # 6 months; the schema has no "months" (USA 4-2 uses 26 weeks too)
    ("3-3", "Paid Sick Leave", "paid_sick_leave", "time_off", ["all"], "paid",
     ("Employees with illness or injury confirmed by a medical sick leave certificate; up to 4 months, first 5 days "
      "paid by the employer, the rest by the Social Insurance Fund (50-100% by seniority)", None)),
    ("3-4", "Pregnancy/Maternity Leave", "pregnancy_maternity_leave", "leave_of_absence", ["all"], "paid",
     ("Pregnant employees: 126 paid calendar days (70 before the due date, 56 after), 100% of average salary from "
      "the Social Insurance Fund", None)),
    ("3-5", "Paternity Leave", "paternity_leave", "leave_of_absence", ["all"], "unpaid",
     ("Fathers: 2 weeks of unpaid leave for the birth of a child; may take over the mother's maternity leave if she "
      "returned to work", None)),
    # Unnumbered in the PDF; numbered after the last section like the USA handbook (5-18).
    ("3-6", "A Few Closing Words", "a_few_closing_words", "company", ["all"], "not_applicable", None),
]

FIXES = [  # PDF text-extraction artefacts (not edits of the handbook wording)
    ("Employee s ", "Employees "), ("endeavor t o", "endeavor to"), ("In ca\nse", "In case"),
    ("e- mails", "e-mails"), ("non- hazardous", "non-hazardous"), ("Company- furnished", "Company-furnished"),
    ("short -term", "short-term"),
    ("30-day period \n", "30-day period.\n"),  # a missing full stop merges two paragraphs
]
NAMES = [  # anonymised the same way as the USA chunks
    ("MGNY Consulting", "It Company"), ("MGNY Ukraine office", "It Company Ukraine office"),
    ("MGNY's group", "It Company's group"), ("MGNY's overarching", "It Company's overarching"),
    ("Michael, Geylik", "John Carter"),
]
SUBHEADINGS = {  # lines that stay on their own (no full stop at the end)
    "Just Cause", "Why?", "Expertise", "Innovation", "Transparency", "Breadth", "Fairness", "Client Amazement",
    "The Long View", "Definition of Harassment", "Definition of Retaliation", "Investigation Procedures",
    "Prohibited Conduct", "Procedures for Reporting a Threat", "Hours of Work", "Location", "Duties", "Equipment",
    "Return of Company Property", "Expenses", "Confidentiality", "Floating Holidays", "CEO", "John Carter",
}
BULLET = "●"


def extract_text(pdf: Path) -> str:
    from pypdf import PdfReader  # imported here so --help works without pypdf

    return "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)


def to_paragraphs(raw: str) -> str:
    """Join PDF-wrapped lines into paragraphs; list items and subheadings stay on their own lines."""
    for a, b in FIXES:
        raw = raw.replace(a, b)
    for a, b in NAMES:
        raw = re.sub(re.escape(a).replace(r"\ ", r"\s+"), b, raw)
    if "MGNY" in raw:
        raise ValueError(f"company name left after anonymisation: {re.findall(r'.{30}MGNY.{30}', raw)}")
    paras: list[str] = []
    for line in (re.sub(r"\s{2,}", " ", l.strip()) for l in raw.splitlines()):
        if not line:
            continue
        starts_new = (
            not paras
            or line.startswith(BULLET)
            or re.match(r"^\d+\.\s", line) is not None
            or re.search(r"[.:;!?]$", paras[-1]) is not None
            or line in SUBHEADINGS
            or paras[-1] in SUBHEADINGS
            or (paras[-1].startswith(BULLET) and line[:1].isupper())  # wrapped bullets continue in lowercase
        )
        if starts_new:
            paras.append(line)
        else:
            joiner = "" if paras[-1].endswith("-") and not paras[-1].endswith(" -") else " "
            paras[-1] += joiner + line
    return "\n".join(re.sub(rf"^{BULLET}\s*", "- ", p).strip() for p in paras)


def handbook_body(text: str) -> str:
    """Text from section 1-1 up to the acknowledgment form, with headings normalised to '\\n<id>. <title>'."""
    text = text.replace("", BULLET)  # Wingdings check-mark bullet
    body = text[text.rindex("1-1. Introduction"):]  # the last one: the first is in the table of contents
    body = body[: body.index("General Handbook Acknowledgment")]
    body = re.sub(r"\n(\d)\n-(\d+)\.", r"\n\1-\2.", body)  # "2\n-7. Attendance" -> "2-7. Attendance"
    body = re.sub(r"(\n\d-\d+\.)\n\s*", r"\1 ", body)  # "2-1.\n Employee Classifications"
    body = body.replace("\nA Few Closing Words", "\n3-6. A Few Closing Words")
    for heading in ("Section 2 - Operation Policies", "Section 3- Benefits"):
        body = body.replace(heading, "")
    return "\n" + body


def localize(s: str, country: str) -> str:
    """Swap the source country's name/adjective for the target one ('Ukrainian' before 'Ukraine')."""
    if country == SOURCE_COUNTRY:
        return s
    (src_name, src_adj), (dst_name, dst_adj) = COUNTRY_WORDS[SOURCE_COUNTRY], COUNTRY_WORDS[country]
    return s.replace(src_adj, dst_adj).replace(src_name, dst_name)


def build_chunks(text: str, *, country: str, sub_company: list[str]) -> list[tuple[str, dict]]:
    body = handbook_body(text)
    prefix = COUNTRIES[country]
    chunks = []
    for i, (cid, title, slug, category, applies_to, paid, elig) in enumerate(META):
        start = re.search(rf"\n{re.escape(cid)}\.\s", body)
        if not start:
            raise ValueError(f"section {cid} ({title}) not found in the PDF text")
        nxt = re.search(rf"\n{re.escape(META[i + 1][0])}\.\s", body) if i + 1 < len(META) else None
        section_text = body[start.end(): nxt.start() if nxt else len(body)]
        section_text = section_text[section_text.find("\n") + 1:]  # drop the heading line
        txt = localize(to_paragraphs(section_text), country)  # after anonymisation: NAMES match "MGNY Ukraine office"
        major, minor = (int(n) for n in cid.split("-"))
        data = {
            "id": cid,
            "title": title,
            "section": {"number": major, "title": SECTIONS[major]},
            "category": category,
            "country": country,
            "sub_company": sub_company,
            "applies_to": applies_to,
            "eligibility": None if elig is None else {"who": localize(elig[0], country), "min_tenure": elig[1]},
            "paid_status": paid,
            "source": "Handbook",
            "text": txt,
            "word_count": len(txt.split()),
        }
        chunks.append((f"{prefix}_{major:02d}-{minor:02d}_{slug}.json", data))
    return chunks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pdf", type=Path)
    p.add_argument("--country", required=True, choices=sorted(COUNTRIES))
    p.add_argument("--sub-company", required=True, action="append", choices=SUB_COMPANIES,
                   help="repeat for several subsidiaries")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    p.add_argument("--dry-run", action="store_true", help="print file names and word counts, write nothing")
    p.add_argument("--force", action="store_true", help="overwrite existing chunk files (they may be hand-edited)")
    args = p.parse_args(argv)

    chunks = build_chunks(extract_text(args.pdf), country=args.country, sub_company=list(dict.fromkeys(args.sub_company)))
    existing = [name for name, _ in chunks if (args.out / name).exists()]
    if existing and not args.dry_run and not args.force:
        print(f"{len(existing)} file(s) already exist in {args.out} (e.g. {existing[0]}); "
              "they may be edited by hand — use --force to overwrite", file=sys.stderr)
        return 1
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
    for name, data in chunks:
        if not args.dry_run:
            (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}  words={data['word_count']}")
    print(f"{len(chunks)} chunks {'(dry run)' if args.dry_run else '-> ' + str(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
