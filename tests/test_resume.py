import pytest
from fastapi.testclient import TestClient

from jobfinder import resume_check as rc
from jobfinder.web.app import app
from tests.conftest import make_jobs


@pytest.fixture
def authed():
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/login", data={"username": "admin", "password": "test-pass"}, follow_redirects=False).status_code == 303
        yield c


def make_pdf(items) -> bytes:
    """Minimal one-page text PDF. items: (x, y, text) tuples, Helvetica 11pt."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "\n".join(f"BT /F1 11 Tf {x} {y} Td ({esc(t)}) Tj ET" for x, y, t in items).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)


GOOD = ["Asha Rao", "asha.rao@example.com | +91 98765 43210 | github.com/asharao | linkedin.com/in/asharao",
        "EXPERIENCE", "Software Engineer Intern, Acme Labs  Jun 2023 - Aug 2023",
        "- Built a REST API with Python and Django serving 5000 users",
        "- Reduced page load time by 40% by adding Redis caching",
        "- Wrote unit tests with pytest covering 90% of modules",
        "- Deployed services on AWS using Docker",
        "EDUCATION", "B.Tech in Computer Science, Anna University, 2023  CGPA 8.4",
        "SKILLS", "Python, Django, Redis, AWS, Docker",
        "PROJECTS", "Job Tracker", "- Developed a Flask app with PostgreSQL for tracking applications"]


def run(lines, x=50):
    return rc.analyse(rc.read_pdf(make_pdf([(x, 760 - 16 * i, t) for i, t in enumerate(lines)])))


def msgs(rep, level=None):
    return [n["msg"] for n in rep["notes"] if level in (None, n["level"])]


def test_clean_single_column_resume_extracts_fields_and_has_no_failures():
    rep = run(GOOD)
    p = rep["parsed"]
    assert p["name"] == "Asha Rao" and p["contact"]["email"] == "asha.rao@example.com"
    assert p["contact"]["phone"] and p["contact"]["github"] and p["contact"]["linkedin"]
    assert {"experience", "education", "skills", "projects"} <= set(p["sections"])
    assert p["experience"] == [{"title": "Software Engineer Intern", "company": "Acme Labs", "from": "Jun 2023", "to": "Aug 2023"}]
    assert p["education"] and p["education"][0]["year"] == "2023"
    assert {"Python", "Django", "AWS"} <= set(p["skills"]) and p["bullets"] == 5
    assert not msgs(rep, "fail")


def test_two_column_layout_is_a_failure():
    items = []
    for i in range(12):
        items += [(50, 760 - 16 * i, f"Left column line {i}"), (330, 760 - 16 * i, f"Right column line {i}")]
    rep = rc.analyse(rc.read_pdf(make_pdf(items)))
    assert any("columns" in m for m in msgs(rep, "fail"))


def test_pdf_without_text_fails_and_missing_contact_is_flagged():
    rep = rc.analyse(rc.read_pdf(make_pdf([])))
    assert any("Almost no text" in m for m in msgs(rep, "fail"))
    rep = run(["Asha Rao", "EXPERIENCE", "Intern, Acme  Jun 2023 - Aug 2023", "SKILLS", "Python"])
    assert any("email" in m for m in msgs(rep, "fail"))


def doc(text, pages=1):
    return {"plain": [text], "layout": [text], "n_pages": pages, "images": 0, "links": []}


def test_content_checks_flag_weak_bullets_dates_and_unproven_skills():
    text = "\n".join(["Asha Rao", "a@b.co", "EXPERIENCE", "Developer at Acme  06/2022 - 08/2023",
                      "- Responsible for the website", "- Worked on many tasks for the team daily",
                      "- Helped the team with testing things", "- Was part of the QA process too",
                      "SKILLS", "Python, Kubernetes, Terraform"])
    m = msgs(rc.analyse(doc(text)))
    assert any("weak phrasing" in x for x in m)
    assert any("MM/YYYY" in x for x in m)
    assert any("Listed but never shown" in x and "Kubernetes" in x for x in m)
    assert any("action verb" in x for x in m) and any("have a number" in x for x in m)


def test_word_per_line_plain_text_is_rebuilt_from_layout_lines():
    real = ["A YUSH  S INGH", "(+91) 7028378954 | a@b.co", "E XPERIENCE", "Intern | Acme  May 2024 – Oct 2024",
            "● Led the build of a tool used by 200 staff", "E DUCATION", "B.Tech, Pune University, 2024", "S KILLS", "Python"]
    d = {"plain": ["\n".join(" ".join(real).split())], "layout": ["\n".join(real)], "n_pages": 1, "images": 0, "links": []}
    p = rc.analyse(d)["parsed"]
    assert p["name"] == "AYUSH SINGH" and p["contact"]["phone"].endswith("7028378954")
    assert {"experience", "education", "skills"} <= set(p["sections"])
    assert p["experience"] and p["experience"][0]["company"] == "Acme" and p["education"]


def test_too_many_pages_and_icon_glyphs():
    m = msgs(rc.analyse(doc("Asha Rao\n a@b.co", pages=3)), "fail")
    assert any("3 pages" in x for x in m)
    assert any("Icon-font" in x for x in msgs(rc.analyse(doc("Asha Rao\n a@b.co"))))


def test_market_gap_needs_enough_jobs_and_ranks_missing_skills():
    few = make_jobs(*[{} for _ in range(5)])
    from jobfinder import skills
    assert rc.market(skills.add_skills(few), {"Python"}) is None
    rows = [{"description": "Python Django Docker AWS Redis developer needed. " * 3} for _ in range(25)]
    df = skills.add_skills(make_jobs(*rows))
    df["exp_min"] = None
    mk = rc.market(df, {"Python", "Django"})
    assert mk and mk["jobs"] == 25 and 0 < mk["cover"] < 100
    assert {g["skill"] for g in mk["gaps"]} >= {"Docker", "AWS", "Redis"}
    assert rc.overall([], mk)["total"] == round(100 * .4 + 100 * .3 + mk["cover"] * .3)


def test_resume_page_and_api(authed):
    assert authed.get("/resume").status_code == 200
    r = authed.post("/resume/upload", files={"file": ("cv.pdf", make_pdf([(50, 760 - 16 * i, t) for i, t in enumerate(GOOD)]))},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/resume"
    page = authed.get("/resume").text
    assert "Fix first" in page and "asha.rao@example.com" in page and "Acme Labs" in page
    bad = authed.post("/resume/upload", files={"file": ("cv.pdf", b"nope")}, follow_redirects=False)
    assert "PDF" in bad.headers["location"]
