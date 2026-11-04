from datetime import date

from jobfinder.experience import job_years, normalize, parse_experience
from jobfinder.skills import SKILLS, extract


def test_normalize_collapses_pdf_word_per_line_and_split_headings():
    assert normalize("E\nXPERIENCE\nMay\n2024") == "EXPERIENCE May 2024"


def test_experience_sums_months_and_merges_overlaps():
    text = "Intern | A May 2024 - Oct 2024 ... Dev Jan 2025 - Jun 2025 ... Dev2 Mar 2025 - Aug 2025"
    exp = parse_experience(text, today=date(2026, 1, 1))
    assert exp["months"] == 6 + 8  # May-Oct (6) + Jan-Aug merged (8)


def test_experience_present_uses_today_and_extracts_roles():
    text = "July 2026 - present Senior Software Developer | Acme"
    exp = parse_experience(text, today=date(2026, 11, 1))
    assert exp["months"] == 5
    assert exp["roles"][0]["title"] == "Senior Software Developer"


def test_experience_ignores_reversed_ranges():
    assert parse_experience("Dec 2025 - Jan 2024")["months"] == 0


def test_job_years_variants():
    assert job_years("0-2 years of experience") == (0.0, 2.0)
    assert job_years("Minimum 3+ years required") == (3.0, 3.0)
    assert job_years("freshers welcome") == (0.0, 0.0)
    assert job_years("no mention at all") == (None, None)


def test_extract_finds_known_skills():
    found = extract("Build REST APIs with Django and PostgreSQL on AWS. Node.js a plus. C++ and C# too.")
    assert {"Django", "PostgreSQL", "AWS", "Node.js", "C++", "C#", "REST APIs"} <= found


def test_extract_avoids_common_false_positives():
    prose = "We value testing mindset, will express interest, and spring into action. Contact our API team."
    found = extract(prose)
    assert "Testing" not in found and "REST APIs" not in found and "Express" not in found


def test_every_skill_regex_compiles_and_names_are_unique():
    assert len(SKILLS) == len(set(SKILLS))
    for name in SKILLS:
        extract(name)
