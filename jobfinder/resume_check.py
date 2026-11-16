"""Rule-based resume checker. It reads a PDF the way a basic ATS does (plain text in content order, no layout
understanding), shows what it could extract, and flags what is likely to go wrong. No LLM, and it is a heuristic:
real parsers (Workday, Greenhouse, ...) are proprietary and differ from each other."""
import io
import re
from collections import Counter

from . import skills as skillmod
from .experience import RANGE, ROLE_WORDS

MAX_PAGES = 5

_HEAD = {k: re.compile(v) for k, v in {
    "experience": r"(?:work |professional |relevant )?(?:experience|employment(?: history)?|internships?)",
    "education": r"education(?:al)?(?: qualifications?| background)?|academics?",
    "skills": r"(?:technical |key |core )?skills|technologies|tech stack",
    "projects": r"(?:academic |personal |key )?projects",
    "summary": r"(?:professional )?(?:summary|profile|objective|about me)",
    "certifications": r"certifications?|courses|licenses?",
    "achievements": r"achievements?|awards?|honou?rs|accomplishments|activities|extracurricular(?:s| activities)?"
                    r"|positions of responsibility",
}.items()}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\(?\+?\d[\d\s().-]{8,16}\d")
DEGREE = re.compile(r"\b(b\.?\s?tech|b\.?\s?e\b|bca|mca|m\.?\s?tech|b\.?\s?sc|m\.?\s?sc|b\.?\s?com|bachelor|master|mba|"
                    r"diploma|12th|hsc|10th|ssc)\b", re.I)
BULLET = re.compile(r"^[•●▪◦‣▸►·*\-–]\s*")
VERBS = set("""built developed designed implemented created led managed optimized optimised reduced improved deployed
automated integrated migrated tested wrote launched delivered collaborated analyzed analysed architected refactored
debugged maintained configured contributed engineered established enhanced executed resolved streamlined trained scaled
secured spearheaded achieved authored coordinated documented drove mentored monitored owned planned researched shipped
simplified solved supported upgraded utilized wrote increased decreased cut ran set""".split())
WEAK = re.compile(r"\b(responsible for|worked on|helped|assisted|duties (?:included|were)|involved in|tasked with|"
                  r"participated in)\b", re.I)
FLUFF = re.compile(r"\b(hard.?working|team player|go.?getter|results.?driven|self.?motivated|passionate|"
                   r"detail.?oriented|dynamic|synergy|fast learner)\b", re.I)
METRIC = re.compile(r"\d+(?:\.\d+)?\s?(?:%|x\b|k\b|ms\b|\+)|\b(?!(?:19|20)\d\d\b)\d{2,}\b")
ICON_GLYPH = re.compile(r"[-�]|\(cid:\d+\)")
DATE_FORMS = {"Mon YYYY": re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d\d", re.I),
              "MM/YYYY": re.compile(r"\b\d{1,2}/(?:19|20)\d\d\b"),
              "YYYY only": re.compile(r"(?<![/\w])(?:19|20)\d\d\s*[-–—]\s*(?:(?:19|20)\d\d|present|current)\b", re.I)}


def read_pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    pages = list(r.pages)[:MAX_PAGES]
    images, links = 0, []
    for p in pages:
        try:
            images += len(p.images)
        except Exception:
            pass
        for a in p.get("/Annots") or []:
            try:
                uri = (a.get_object().get("/A") or {}).get_object().get("/URI")
                if uri:
                    links.append(str(uri))
            except Exception:
                pass
    return {"plain": [p.extract_text() or "" for p in pages],
            "layout": [p.extract_text(extraction_mode="layout") or "" for p in pages],
            "n_pages": len(r.pages), "images": images, "links": links}


def _lines(text: str) -> list[str]:
    out = (re.sub(r"\b([A-Z]) ([A-Z]{3,})\b", r"\1\2", ln.replace("\xa0", " ")).strip() for ln in text.splitlines())
    return [ln for ln in out if ln]


def _heading(ln: str) -> str | None:
    t = ln.strip(" :•|-–").lower()
    if len(t) > 40 or len(t.split()) > 4:
        return None
    return next((k for k, rx in _HEAD.items() if rx.fullmatch(t)), None)


def _sections(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    secs: dict[str, list[str]] = {"top": []}
    odd, cur = [], "top"
    for i, ln in enumerate(lines):
        h = _heading(ln)
        if h:
            cur = h
            secs.setdefault(h, [])
        elif i and ln.isupper() and 1 <= len(ln.split()) <= 4 and 4 <= len(ln) <= 30 and not re.search(r"[\d@/|]", ln):
            odd.append(ln)  # all-caps line that is not a known heading: may be one, may be a company name
        else:
            secs[cur].append(ln)
    return secs, odd


def _split_role(s: str) -> tuple[str | None, str | None]:
    parts = [p.strip() for p in re.split(r"\s+[|@–—-]\s+|,\s+|\s+at\s+", s) if p.strip()]
    title = next((p for p in parts if re.search(ROLE_WORDS, p, re.I)), None)
    return title, next((p for p in parts if p != title), None)


def _experience(lines: list[str]) -> list[dict]:
    out = []
    for i, ln in enumerate(lines):
        m = RANGE.search(ln)
        if not m:
            continue
        side = [s for s in (ln[:m.start()], ln[m.end():]) if s.strip(" |,-–—•●()")]
        text = " | ".join(s.strip(" |,-–—•●") for s in side) or (lines[i - 1] if i else "")
        title, company = _split_role(text)
        out.append({"title": title, "company": company, "from": re.split(r"\s*[-–—]\s*", m.group(0))[0],
                    "to": "present" if m.group(5) else f"{m.group(3)} {m.group(4)}"})
    return out


def _bullets(lines: list[str]) -> list[str]:
    """Join wrapped lines when the section uses bullet markers; otherwise treat each long line as one point."""
    if any(BULLET.match(ln) for ln in lines):
        out: list[str] = []
        for ln in lines:
            if BULLET.match(ln):
                out.append(BULLET.sub("", ln))
            elif out and not RANGE.search(ln) and not ln.isupper() and len(ln.split()) > 2:
                out[-1] += " " + ln
        return out
    return [ln for ln in lines if len(ln.split()) >= 6 and not RANGE.search(ln)]


def _columns(layouts: list[str]) -> bool:
    """Aligned runs of 4+ spaces on many lines mean columns or a table."""
    starts = Counter()
    for pg in layouts:
        for ln in pg.splitlines():
            m = re.match(r"^\s*\S.*?\S {4,}(?=\S)", ln)
            if m:
                starts[m.end() // 3] += 1
    return bool(starts) and starts.most_common(1)[0][1] >= 6


def _f(level: str, area: str, msg: str, fix: str = "") -> dict:
    return {"level": level, "area": area, "msg": msg, "fix": fix}


def analyse(doc: dict) -> dict:
    text = "\n".join(doc["plain"])
    # Plain extraction can come out one word per line (common with LaTeX/Canva exports); the layout pass
    # rebuilds real lines from word positions, so parse structure from that.
    lines = [re.sub(r"\s{3,}", "   ", ln) for ln in _lines("\n".join(doc["layout"]))] or _lines(text)
    words = len(text.split())
    secs, odd = _sections(lines)
    notes: list[dict] = []
    n = notes.append

    # ---- what an ATS would extract
    top = " ".join(lines[:8])
    email = EMAIL.search(text)
    contact = {"email": email.group(0) if email else None,
               "phone": next((m.group(0).strip() for m in PHONE.finditer(top + " " + " ".join(secs["top"]))
                              if 10 <= len(re.sub(r"\D", "", m.group(0))) <= 13), None)}
    blob = text + " " + " ".join(doc["links"])
    contact["linkedin"] = bool(re.search(r"linkedin\.com/in/", blob, re.I))
    contact["github"] = bool(re.search(r"github\.com/[\w-]+", blob, re.I))
    first = re.sub(r"\s+", " ", lines[0]) if lines else ""
    name = first if 2 <= len(first.split()) <= 4 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", first) else None
    exp = _experience(secs.get("experience", []))
    edu = [{"line": ln[:110], "year": (re.findall(r"(?:19|20)\d\d", ln) or [None])[-1]}
           for ln in secs.get("education", []) if DEGREE.search(ln)]
    found_skills = sorted(skillmod.extract(text))
    points = _bullets(secs.get("experience", []) + secs.get("projects", []))
    parsed = {"name": name, "contact": contact, "sections": [k for k in secs if k != "top" and secs[k]],
              "experience": exp, "education": edu, "skills": found_skills, "bullets": len(points)}

    # ---- does it parse?
    if words < 40:
        n(_f("fail", "parse", "Almost no text could be read from this PDF.",
             "It is probably a scan or exported as images. Export a text PDF from Word, Docs or LaTeX."))
    if _columns(doc["layout"]):
        n(_f("fail", "parse", "Two columns or a table layout detected. Parsers read across the page and mix the columns.",
             "Use a single column. Move sidebar content (skills, contact) into normal sections."))
    if ICON_GLYPH.search(text):
        n(_f("warn", "parse", "Icon-font symbols found in the text. They come out as garbage characters.",
             "Replace icons with plain words (Email, GitHub) or remove them."))
    if doc["images"]:
        n(_f("warn", "parse", f"{doc['images']} image(s) in the file. ATS software ignores images.",
             "Keep anything important (skills, ratings, contact) as text. Skip the photo."))
    if doc["n_pages"] > 2:
        n(_f("fail", "parse", f"{doc['n_pages']} pages. Recruiters give a fresher resume seconds.", "Cut it to one page."))
    elif doc["n_pages"] == 2 and words < 700:
        n(_f("warn", "parse", "Two pages with little text.", "Aim for one page at this experience level."))
    for key, label in (("experience", "Experience"), ("education", "Education"), ("skills", "Skills")):
        if not secs.get(key):
            n(_f("warn" if key == "experience" and secs.get("projects") else "fail", "parse",
                 f"No '{label}' section found.", f"Add a plain heading named exactly '{label}'."))
    for h in odd[:3]:
        n(_f("warn", "parse", f"'{h.title()}' may not be recognised as a section heading.",
             "Use standard names: Experience, Education, Skills, Projects."))
    if not contact["email"]:
        n(_f("fail", "parse", "No email address found.", "Put your email as plain text at the top, not in a header or image."))
    if not contact["phone"]:
        n(_f("warn", "parse", "No phone number found.", "Add it as plain text at the top."))
    if not name:
        n(_f("warn", "parse", "Could not tell which line is your name.", "Put just your name on the first line."))
    if not contact["github"]:
        n(_f("warn", "parse", "No GitHub link for a developer resume.", "Add your GitHub profile URL as visible text."))
    if not contact["linkedin"]:
        n(_f("warn", "parse", "No LinkedIn link.", "Add your LinkedIn URL as visible text."))
    forms = [k for k, rx in DATE_FORMS.items() if rx.search(text)]
    if len(forms) > 1:
        n(_f("warn", "parse", "Dates use mixed formats (" + ", ".join(forms) + ").", "Use one format everywhere, e.g. 'Jun 2023 – Aug 2024'."))
    elif forms and forms != ["Mon YYYY"]:
        n(_f("warn", "parse", f"Dates are in '{forms[0]}' form. Month names are read most reliably, and this app's own experience calculation needs them.",
             "Write dates as 'Jun 2023 – Aug 2024'."))
    if secs.get("experience") and not exp:
        n(_f("warn", "parse", "No job dates could be read, so experience length cannot be computed.", "Put 'Mon YYYY – Mon YYYY' on each role."))
    for e in exp:
        if not e["title"] or not e["company"]:
            n(_f("warn", "parse", f"Role at {e['from']} – {e['to']}: " + ("title" if not e["title"] else "company") + " not clearly separable.",
                 "Put title and company on one line, e.g. 'Software Engineer Intern, Acme  Jun 2023 – Aug 2024'."))
            break

    # ---- does it read well?
    if len(points) < 4 and words >= 40:
        n(_f("warn", "content", f"Only {len(points)} achievement lines found in Experience and Projects.",
             "Use bullets (3 to 5 per role or project), one achievement each."))
    elif points:
        lead = sum(1 for b in points if (b.split() or [""])[0].lower().strip(",:") in VERBS or (b.split() or [""])[0].lower().endswith("ed"))
        if lead < 0.6 * len(points):
            n(_f("warn", "content", f"Only {lead} of {len(points)} bullets start with an action verb.", "Start each with Built, Reduced, Led, Shipped..."))
        num = sum(1 for b in points if METRIC.search(b))
        if num < 0.3 * len(points):
            n(_f("warn", "content", f"Only {num} of {len(points)} bullets have a number.",
                 "Add scale or impact: users, requests, % faster, tests, hours saved."))
        weak = [b for b in points if WEAK.search(b)]
        if weak:
            n(_f("warn", "content", f"{len(weak)} bullet(s) use weak phrasing ('responsible for', 'worked on', 'helped').",
                 "Say what you did and what changed. Example: " + weak[0][:70]))
        long_ = [b for b in points if len(b.split()) > 40]
        if long_:
            n(_f("warn", "content", f"{len(long_)} bullet(s) run past 40 words.", "Keep each to one or two lines."))
        if sum(1 for b in points if re.match(r"(I|My|We)\b", b)) >= 2:
            n(_f("warn", "content", "Bullets written in first person.", "Drop 'I' and 'my'."))
    if len(FLUFF.findall(text)) >= 2:
        n(_f("warn", "content", "Generic buzzwords ('team player', 'passionate', 'hard-working').", "Replace with something you did."))
    if words > 800:
        n(_f("warn", "content", f"{words} words is long for this level.", "Trim older or minor items."))
    elif 40 <= words < 180:
        n(_f("warn", "content", f"Only {words} words.", "Add projects, or detail on what you built."))
    sk, work = skillmod.extract(" ".join(secs.get("skills", []))), skillmod.extract(" ".join(secs.get("experience", []) + secs.get("projects", [])))
    unproven = sorted(sk - work)
    if sk and (secs.get("experience") or secs.get("projects")) and unproven:
        n(_f("warn", "content", f"Listed but never shown in a project or job: {', '.join(unproven[:6])}.",
             "Mention each in a bullet that proves it, or drop it from the list."))
    if not [x for x in notes if x["level"] == "fail"]:
        n(_f("ok", "parse", "Extractable text, standard sections and contact details."))
    return {"parsed": parsed, "notes": notes, "words": words, "pages": doc["n_pages"], "text": text}


def score(notes: list[dict], area: str) -> int:
    pen = {"fail": 25 if area == "parse" else 15, "warn": 8 if area == "parse" else 6}
    return max(0, 100 - sum(pen.get(x["level"], 0) for x in notes if x["area"] == area))


def market(df, mine: set[str], years: float | None = None, n: int = 8) -> dict | None:
    """How well the resume covers what postings ask for, and the biggest gaps. None when there is too little data."""
    if len(df) and years is not None:
        df = df[df["exp_min"].isna() | (df["exp_min"] <= years + 1)]
    d = skillmod.demand(df) if len(df) else None
    if d is None or d.empty or int(d["jobs"].max()) < 20:
        return None
    top = d.head(15)
    cover = top[top["skill"].isin(mine)]["share_%"].sum() / top["share_%"].sum() * 100
    gaps = d[~d["skill"].isin(mine)].head(n)
    return {"cover": round(cover), "jobs": int(len(df)),
            "gaps": [{"skill": r["skill"], "share": float(r["share_%"]), "jobs": int(r["jobs"])} for r in gaps.to_dict("records")]}


def overall(notes: list[dict], mkt: dict | None) -> dict:
    parts = {"parse": (score(notes, "parse"), .4), "content": (score(notes, "content"), .3)}
    if mkt:
        parts["market"] = (mkt["cover"], .3)
    total = sum(w for _, w in parts.values())
    return {"total": round(sum(s * w for s, w in parts.values()) / total), **{k: s for k, (s, _) in parts.items()}}
