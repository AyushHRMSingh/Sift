import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_M = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
RANGE = re.compile(rf"{_M}\s+(\d{{4}})\s*[-–—]\s*(?:{_M}\s+(\d{{4}})|(present|current|now|ongoing))", re.I)
ROLE_WORDS = r"(intern|engineer|developer|sde|analyst|programmer|trainee|consultant|architect|lead|manager|designer)"


def normalize(text: str) -> str:
    """PDFs often come out one word per line, and small-caps headings split as 'E XPERIENCE'."""
    t = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r"\b([A-Z]) ([A-Z]{3,})\b", r"\1\2", t)


def _idx(month: str, year: str) -> int:
    return int(year) * 12 + MONTHS[month[:3].lower()]


def parse_experience(text: str, today: date | None = None) -> dict:
    """Roles with date ranges, and total months worked (overlaps merged)."""
    t = normalize(text)
    today = today or date.today()
    spans, roles = [], []
    for m in RANGE.finditer(t):
        start = _idx(m.group(1), m.group(2))
        end = today.year * 12 + today.month if m.group(5) else _idx(m.group(3), m.group(4))
        if end < start:
            continue
        spans.append((start, end + 1))  # inclusive of both months
        tail = t[m.end():m.end() + 120]
        tail = re.sub(r"^\s*\(\d+\s*months?\)\s*", "", tail, flags=re.I)
        title = re.split(r"[|●•]", tail)[0].strip()
        if re.search(ROLE_WORDS, title, re.I) and len(title) < 80:
            roles.append({"title": title, "from": m.group(0).split("–")[0].strip(),
                          "to": "present" if m.group(5) else f"{m.group(3)} {m.group(4)}"})
    months, last = 0, None
    for s, e in sorted(spans):
        if last is None or s > last:
            months += e - s
            last = e
        elif e > last:
            months += e - last
            last = e
    return {"months": months, "years": round(months / 12, 1), "roles": roles}


JOB_RANGE = re.compile(r"(\d{1,2})\s*(?:\+|to|-|–)\s*(\d{1,2})?\s*(?:\+\s*)?(?:years?|yrs?)", re.I)
JOB_MIN = re.compile(r"(?:minimum|at least|min\.?)?\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I)


def job_years(text: str) -> tuple[float | None, float | None]:
    """(min, max) years of experience a posting asks for, or (None, None)."""
    t = normalize(text)[:6000]
    if re.search(r"\b(freshers?|0 ?years)\b", t, re.I) and not JOB_MIN.search(t):
        return 0.0, 0.0
    m = JOB_RANGE.search(t)
    if m:
        lo = float(m.group(1))
        return lo, float(m.group(2) or lo)
    m = JOB_MIN.search(t)
    return (float(m.group(1)), float(m.group(1))) if m else (None, None)
