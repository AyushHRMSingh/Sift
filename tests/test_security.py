import re

import pytest
from fastapi.testclient import TestClient

from jobfinder import settings, store
from jobfinder.web import auth, security
from jobfinder.web.app import app
from tests.conftest import make_jobs

LOGIN = {"username": "admin", "password": "test-pass"}


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    auth._failures.clear()
    security.anon_limiter.hits.clear()
    security.user_limiter.hits.clear()
    monkeypatch.setattr(auth, "FAIL_DELAY", 0)
    monkeypatch.setattr(security, "LOOPBACK", security.LOOPBACK | {"testclient"})  # TestClient's peer address
    yield


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def authed(client):
    client.post("/login", data=LOGIN)
    return client


def test_security_headers_on_every_kind_of_response(client, authed):
    for r in (client.get("/login"), client.get("/healthz"), authed.get("/"), authed.get("/nope")):
        h = r.headers
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"
        assert "noindex" in h["x-robots-tag"]
        assert "server" not in h or "uvicorn" not in h["server"].lower()


def test_csp_nonce_matches_every_inline_script_and_is_fresh_per_request(authed):
    con = store.connect()
    store.upsert(con, make_jobs({}))
    con.close()
    r1, r2 = authed.get("/"), authed.get("/")
    nonce = re.search(r"script-src 'nonce-([^']+)'", r1.headers["content-security-policy"]).group(1)
    scripts = re.findall(r"<script([^>]*)>", r1.text)
    assert scripts and all(f'nonce="{nonce}"' in s for s in scripts)
    assert nonce not in r2.headers["content-security-policy"]
    assert "'unsafe-inline'" not in re.search(r"script-src[^;]*", r1.headers["content-security-policy"]).group(0)


def test_robots_txt_blocks_everything_and_needs_no_login(client):
    assert client.get("/robots.txt").text.strip().endswith("Disallow: /")


def test_cross_site_post_is_blocked_but_same_site_works(authed):
    bad = authed.post("/undo", headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert bad.status_code == 403
    assert authed.post("/undo", headers={"origin": "https://testserver"}, follow_redirects=False).status_code == 303
    assert authed.post("/undo", headers={"origin": "null"}, follow_redirects=False).status_code == 403


def test_public_url_origin_is_trusted_for_proxies_that_rewrite_host(authed, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://jobs.example.com")
    r = authed.post("/undo", headers={"origin": "https://jobs.example.com"}, follow_redirects=False)
    assert r.status_code == 303


def test_login_lockout_is_per_client_so_a_bot_cannot_lock_you_out(client):
    bot = {"cf-connecting-ip": "203.0.113.9"}
    for _ in range(auth.MAX_FAILS):
        client.post("/login", data={**LOGIN, "password": "x"}, headers=bot)
    assert client.post("/login", data=LOGIN, headers=bot).status_code == 429          # the bot is locked out
    assert client.post("/login", data=LOGIN, headers={"cf-connecting-ip": "198.51.100.7"}, follow_redirects=False).status_code == 303


def test_anonymous_flood_is_throttled_but_logged_in_user_is_not(client):
    hdr = {"cf-connecting-ip": "203.0.113.50"}
    codes = [client.get("/login", headers=hdr).status_code for _ in range(security.anon_limiter.limit + 5)]
    assert codes[: security.anon_limiter.limit] == [200] * security.anon_limiter.limit and codes[-1] == 429
    client.post("/login", data=LOGIN, headers={"cf-connecting-ip": "198.51.100.1"})
    assert all(client.get("/", headers={"cf-connecting-ip": "198.51.100.1"}).status_code == 200 for _ in range(60))


def test_oversized_request_rejected_before_parsing(authed):
    r = authed.post("/profile/resume", content=b"x", headers={"content-length": str(security.MAX_BODY + 1)})
    assert r.status_code == 413


def test_upload_over_limit_or_not_pdf_is_refused(authed):
    big = b"%PDF-" + b"0" * (5 * 1024 * 1024)
    r = authed.post("/profile/resume", files={"file": ("a.pdf", big)}, follow_redirects=False)
    assert r.status_code == 303 and "5MB" in r.headers["location"]


def test_password_hash_login_and_wrong_password(client, monkeypatch):
    monkeypatch.setattr(settings, "PASSWORD_HASH", auth.hash_password("s3cret-pw"))
    assert auth.verify("s3cret-pw") and not auth.verify("test-pass") and not auth.verify("")
    assert client.post("/login", data={"username": "admin", "password": "s3cret-pw"}, follow_redirects=False).status_code == 303
    monkeypatch.setattr(settings, "PASSWORD_HASH", "garbage")
    assert not auth.verify("anything")


def test_no_secret_or_data_files_are_world_readable():
    for name in (".secret", ".password"):
        path = settings.DATA_DIR / name
        if path.exists():
            assert path.stat().st_mode & 0o077 == 0, name


def test_production_config_sets_secure_cookie_and_hsts(tmp_path):
    """Run a separate process configured like production (SECURE_COOKIES default on)."""
    import os
    import subprocess
    import sys
    code = (
        "from fastapi.testclient import TestClient\n"
        "from jobfinder.web.app import app\n"
        "with TestClient(app, base_url='https://t') as c:\n"
        "    r = c.post('/login', data={'username': 'admin', 'password': 'pw'}, follow_redirects=False)\n"
        "    print(r.headers['set-cookie'].lower()); print(r.headers['strict-transport-security'])\n"
    )
    env = {**os.environ, "DATA_DIR": str(tmp_path), "APP_PASSWORD": "pw", "SECURE_COOKIES": "1"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=settings.ROOT, timeout=60).stdout
    assert all(flag in out for flag in ("httponly", "samesite=lax", "secure", "max-age=31536000")), out
