import asyncio
import io
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import matching, settings, sinks, skills, store
from ..analysis import analyze
from ..config import CITIES, QUERIES, SITES
from . import auth, scheduler, security

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
OPEN_PATHS = {"/login", "/healthz", "/robots.txt"}
logging.basicConfig(level=logging.INFO)


def safe_url(u):
    return u if urlparse(u or "").scheme in ("http", "https") else "#"


templates.env.filters["safe_url"] = safe_url
def plain(text):
    """Scraped descriptions carry markdown; show them as clean text."""
    text = re.sub(r"\*\*|__|\\", "", text or "")
    return re.sub(r"(?m)^(\s*)[*+-]\s+", r"\1- ", text)


def money(v):
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


templates.env.filters["plain"] = plain
templates.env.filters["money"] = money
templates.env.filters["date"] = lambda v: v.strftime("%d %b") if pd.notna(v) else ""


@asynccontextmanager
async def lifespan(app):
    if not settings.PASSWORD_HASH:
        settings.password()  # generate + print credentials on first run
    con = store.connect()
    store.backfill(con)
    removed = store.merge_duplicates(con)
    if removed:
        logging.getLogger("jobfinder").info("merged %d duplicate jobs", removed)
    con.close()
    tasks = [asyncio.create_task(scheduler.loop()), asyncio.create_task(scheduler.reminder_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path in OPEN_PATHS or request.session.get("user"):
        return await call_next(request)
    if request.method == "GET" and "application/json" not in request.headers.get("accept", ""):
        return RedirectResponse("/login", 303)
    return JSONResponse({"error": "login required"}, status_code=401)


app.middleware("http")(security.harden)  # outside require_login, so floods are cut before any work


# added last = outermost, so the session is available to the middleware above
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, https_only=settings.SECURE_COOKIES,
                   same_site="lax", max_age=60 * 60 * 24 * 14, session_cookie="jf_session")


def render(request: Request, name: str, **ctx):
    con = store.connect()
    try:
        ctx["counts"] = store.counts(con)
    finally:
        con.close()
    ctx["path"] = request.url.path
    return templates.TemplateResponse(request, name, ctx)


def back(request: Request, default="/"):
    ref = urlparse(request.headers.get("referer", ""))
    if not ref.path.startswith("/") or ref.path.startswith("//"):  # local paths only
        return RedirectResponse(default, 303)
    return RedirectResponse(ref.path + ("?" + ref.query if ref.query else ""), 303)


# ------------------------------------------------------------------ auth
@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None, "path": "/login"})


@app.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = security.client_ip(request)
    if auth.locked(ip):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Too many attempts. Try again in 10 minutes.", "path": "/login"}, 429)
    if auth.check(username, password, ip):
        request.session.clear()
        request.session["user"] = username
        return RedirectResponse("/", 303)
    return templates.TemplateResponse(request, "login.html", {"error": "Wrong username or password.", "path": "/login"}, 401)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


# ------------------------------------------------------------------ swipe
@app.get("/", response_class=HTMLResponse)
def swipe_page(request: Request):
    con = store.connect()
    try:
        prof = matching.Profile(con)
        queue = matching.ranked(store.load(con, "new", description=False), prof)
        job = store.get_job(con, queue.iloc[0]["job_url"]) if len(queue) else None
        if job:
            row = queue.iloc[0]
            job["match"] = None if pd.isna(row["match_%"]) else int(row["match_%"])
            job["missing"] = row["missing"]
            job["have"] = [s for s in job["skills"] if s in prof.skills]
        return render(request, "swipe.html", job=job, left=len(queue), has_profile=bool(prof.skills),
                      can_undo=bool(con.execute("SELECT 1 FROM jobs WHERE swiped_at IS NOT NULL LIMIT 1").fetchone()))
    finally:
        con.close()


@app.post("/swipe")
def swipe(bg: BackgroundTasks, url: str = Form(...), action: str = Form(...)):
    status = {"save": "saved", "pass": "rejected"}.get(action)
    if not status:
        return Response(status_code=400)
    con = store.connect()
    try:
        store.set_status(con, url, status, swipe=True)
        if status == "saved":
            bg.add_task(sinks.notify, "saved", store.get_job(con, url))
    finally:
        con.close()
    return RedirectResponse("/", 303)


@app.post("/undo")
def undo():
    con = store.connect()
    try:
        store.undo_last_swipe(con)
    finally:
        con.close()
    return RedirectResponse("/", 303)


# ------------------------------------------------------------------ saved list
def _list(status: str) -> pd.DataFrame:
    con = store.connect()
    try:
        prof = matching.Profile(con)
        df = skills.add_match(store.load(con, status, description=False), prof.skills, prof.years)
    finally:
        con.close()
    return df.sort_values(["match_%", "date_posted"], ascending=False, na_position="last")


@app.get("/saved", response_class=HTMLResponse)
def saved(request: Request, status: str = "saved"):
    if status not in ("saved", "applied", "rejected"):
        status = "saved"
    return render(request, "saved.html", jobs=_list(status).to_dict("records"), status=status)


@app.get("/saved.csv")
def saved_csv(status: str = "saved"):
    df = _list(status if status in ("saved", "applied", "rejected") else "saved")
    out = df.assign(skills=df["skills"].map(", ".join), missing=df["missing"].map(", ".join))[
        ["title", "company", "search_city", "match_%", "exp_min", "exp_max", "date_posted", "skills", "missing", "job_url"]]
    return Response(out.to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={status}-jobs.csv"})


@app.post("/job/status")
def job_status(request: Request, bg: BackgroundTasks, url: str = Form(...), status: str = Form(...)):
    if status not in store.STATUSES:
        return Response(status_code=400)
    con = store.connect()
    try:
        store.set_status(con, url, status)
        bg.add_task(sinks.notify, "status", store.get_job(con, url))
    finally:
        con.close()
    return back(request, "/saved")


# ------------------------------------------------------------------ analysis
@app.get("/analysis", response_class=HTMLResponse)
def analysis_page(request: Request):
    con = store.connect()
    try:
        prof = matching.Profile(con)
        df = store.load(con)
    finally:
        con.close()
    return render(request, "analysis.html", a=analyze(df, prof.skills, prof.years), has_profile=bool(prof.skills))


# ------------------------------------------------------------------ profile
@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, msg: str = ""):
    con = store.connect()
    try:
        prof = matching.Profile(con)
    finally:
        con.close()
    return render(request, "profile.html", prof=prof, all_skills=list(skills.SKILLS), msg=msg)


@app.post("/profile/resume")
async def upload_resume(file: UploadFile = File(...)):
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024 or not data.startswith(b"%PDF"):
        return RedirectResponse("/profile?msg=Upload+a+PDF+under+5MB", 303)
    try:
        text = skills.pdf_text(io.BytesIO(data))
    except Exception:
        return RedirectResponse("/profile?msg=Could+not+read+that+PDF", 303)
    found = sorted(skills.extract(text))
    con = store.connect()
    try:
        store.save_profile(con, text, found)
        store.set_kv(con, "years", None)
    finally:
        con.close()
    return RedirectResponse(f"/profile?msg=Parsed+{len(found)}+skills", 303)


@app.post("/profile/skills")
async def save_skills(request: Request):
    form = await request.form()
    chosen = [s for s in form.getlist("skills") if s in skills.SKILLS]
    years = str(form.get("years", "")).strip()
    con = store.connect()
    try:
        store.save_profile(con, store.load_profile(con)[0], chosen)
        store.set_kv(con, "years", float(years) if years.replace(".", "", 1).isdigit() else None)
    finally:
        con.close()
    return RedirectResponse("/profile?msg=Saved", 303)


# ------------------------------------------------------------------ scanning
@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, msg: str = ""):
    con = store.connect()
    try:
        return render(request, "scan.html", cfg=scheduler.get_config(con), scans=store.recent_scans(con),
                      state=scheduler.state, msg=msg, discord=bool(settings.DISCORD_WEBHOOK_URL), min_match=settings.DISCORD_MIN_MATCH, reminder_times=settings.REMINDER_TIMES, reminder_tz=settings.REMINDER_TZ, all_queries=sorted(set(QUERIES) | set(scheduler.get_config(con)["queries"])),
                      CITIES=CITIES, SITES=SITES)
    finally:
        con.close()


@app.post("/scan/test-alert")
def test_alert():
    from ..sinks.discord import DiscordSink
    try:
        DiscordSink().test()
        msg = "Test message sent"
    except Exception as e:
        msg = f"Alert test failed: {e}"
    return RedirectResponse(f"/scan?msg={quote(msg)}", 303)


@app.get("/scan/status")
def scan_status():
    return scheduler.state


@app.post("/scan/run")
async def scan_run():
    if not scheduler.state["running"]:
        asyncio.get_running_loop().run_in_executor(None, lambda: scheduler.run_now(manual=True))
    return RedirectResponse("/scan", 303)


@app.post("/scan/config")
async def scan_config(request: Request):
    f = await request.form()
    extra = [q.strip() for q in str(f.get("extra", "")).splitlines() if q.strip()]
    cfg = {
        "enabled": f.get("enabled") == "on",
        "interval_hours": max(0.25, float(f.get("interval_hours") or 1)),
        "queries": list(dict.fromkeys(f.getlist("queries") + extra)),
        "cities": [c for c in f.getlist("cities") if c in CITIES],
        "sites": [s for s in f.getlist("sites") if s in SITES],
        "results": min(100, max(5, int(f.get("results") or 30))),
        "days": min(30, max(1, int(f.get("days") or 7))),
        "full_descriptions": f.get("full_descriptions") == "on",
    }
    con = store.connect()
    try:
        store.set_kv(con, "scan_config", cfg)
    finally:
        con.close()
    return RedirectResponse("/scan", 303)
