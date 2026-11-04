import re

import pytest
from fastapi.testclient import TestClient

from jobfinder import store
from jobfinder.web.app import app
from tests.conftest import make_jobs

LOGIN = {"username": "admin", "password": "test-pass"}


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def authed(client):
    assert client.post("/login", data=LOGIN, follow_redirects=False).status_code == 303
    return client


def seed():
    con = store.connect()
    store.upsert(con, make_jobs({}, {"title": "Backend Developer", "company": "Beta"}))
    con.close()


def test_pages_require_login(client):
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/swipe", data={"url": "x", "action": "save"}).status_code == 401
    assert client.get("/healthz").json() == {"ok": True}


def test_login_rejects_bad_credentials():
    from jobfinder.web import auth
    auth._failures.clear()
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/login", data={**LOGIN, "password": "nope"}).status_code == 401
        assert c.post("/login", data={"username": "root", "password": "test-pass"}).status_code == 401
    auth._failures.clear()


def test_every_page_renders_empty_and_seeded(authed):
    paths = ["/", "/saved", "/saved?status=applied", "/saved?status=bogus", "/analysis", "/profile", "/scan", "/saved.csv", "/scan/status"]
    for p in paths:
        assert authed.get(p).status_code == 200, p
    seed()
    for p in paths:
        assert authed.get(p).status_code == 200, p


def test_swipe_save_shows_in_saved_and_undo_restores(authed):
    seed()
    url = re.search(r'name="url" value="([^"]+)"', authed.get("/").text).group(1)
    assert authed.post("/swipe", data={"url": url, "action": "save"}, follow_redirects=False).status_code == 303
    assert url.rsplit("/", 1)[-1] in authed.get("/saved").text
    authed.post("/undo")
    assert "Nothing here yet" in authed.get("/saved").text


def test_job_status_moves_between_lists_and_rejects_garbage(authed):
    seed()
    url = "https://example.com/job/0"
    authed.post("/swipe", data={"url": url, "action": "save"})
    authed.post("/job/status", data={"url": url, "status": "applied"})
    assert "Backend" not in authed.get("/saved?status=applied").text and "Python Developer" in authed.get("/saved?status=applied").text
    assert authed.post("/job/status", data={"url": url, "status": "zzz"}).status_code == 400
    assert authed.post("/swipe", data={"url": url, "action": "zzz"}).status_code == 400


def test_status_redirect_is_local_only(authed):
    seed()
    for ref, expected in [("https://testserver//evil.com/x", "/saved"), ("https://testserver/saved?status=applied", "/saved?status=applied")]:
        r = authed.post("/job/status", data={"url": "https://example.com/job/0", "status": "saved"},
                        headers={"referer": ref}, follow_redirects=False)
        assert r.headers["location"] == expected


def test_descriptions_are_escaped_and_unsafe_links_neutralised(authed):
    con = store.connect()
    store.upsert(con, make_jobs({"description": "<script>alert(1)</script> Python " * 5, "job_url": "javascript:alert(1)"}))
    con.close()
    page = authed.get("/").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert 'href="javascript:' not in page


def test_resume_upload_validation(authed):
    r = authed.post("/profile/resume", files={"file": ("a.pdf", b"not a pdf")}, follow_redirects=False)
    assert r.status_code == 303 and "PDF" in r.headers["location"]


def test_profile_skills_and_years_save(authed):
    authed.post("/profile/skills", data={"skills": ["Python", "NotASkill"], "years": "1.5"})
    con = store.connect()
    assert store.load_profile(con)[1] == ["Python"] and store.get_kv(con, "years") == 1.5
    con.close()


def test_scan_config_is_clamped_and_saved(authed):
    authed.post("/scan/config", data={"enabled": "on", "interval_hours": "0", "cities": ["Pune", "Atlantis"], "sites": ["indeed"],
                                      "queries": ["SDE 1"], "extra": "go dev\n", "results": "9999", "days": "-4"})
    con = store.connect()
    cfg = store.get_kv(con, "scan_config")
    con.close()
    assert cfg["cities"] == ["Pune"] and cfg["interval_hours"] == 0.25 and cfg["results"] == 100 and cfg["days"] == 1
    assert cfg["queries"] == ["SDE 1", "go dev"]
