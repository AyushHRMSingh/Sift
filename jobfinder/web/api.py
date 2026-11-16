"""JSON API for non-browser clients. Same session cookie as the web portal; native clients send no
Origin header, so the CSRF check lets them through."""
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from .. import matching, sinks, store
from . import auth, security
from .filters import plain

router = APIRouter(prefix="/api")
ACTIONS = {"save": "saved", "research": "research", "pass": "rejected"}
MAX_BATCH, MAX_HELD = 50, 300


def _val(v):
    if isinstance(v, (list, tuple)):
        return list(v)
    return None if v is None or (not isinstance(v, str) and pd.isna(v)) else v


def _job(con, row, prof) -> dict:
    j = store.get_job(con, row["job_url"])
    return {
        "url": j["job_url"], "title": j["title"], "company": j["company"], "city": j["search_city"],
        "site": j["site"], "posted": str(j["date_posted"])[:10] if _val(j["date_posted"]) else None,
        "exp_min": _val(j["exp_min"]), "exp_max": _val(j["exp_max"]),
        "pay": [_val(j["min_amount"]), _val(j["max_amount"]), _val(j["currency"])],
        "skills": j["skills"], "have": [s for s in j["skills"] if s in prof.skills],
        "missing": list(row["missing"]), "match": _val(row["match_%"]) if pd.notna(row["match_%"]) else None,
        "description": plain(j["description"] or ""),
    }


@router.post("/login")
async def login(request: Request):
    body = await request.json()
    ip = security.client_ip(request)
    if auth.locked(ip):
        return JSONResponse({"error": "locked"}, 429)
    if auth.check(str(body.get("username", "")), str(body.get("password", "")), ip):
        request.session.clear()
        request.session["user"] = str(body["username"])
        return {"ok": True}
    return JSONResponse({"error": "bad credentials"}, 401)


@router.post("/queue")
async def queue(request: Request):
    """Next unswiped jobs, best match first, skipping ones the app already holds."""
    body = await request.json()
    limit = max(1, min(MAX_BATCH, int(body.get("limit") or 10)))
    exclude = set(map(str, (body.get("exclude") or [])[:MAX_HELD]))
    con = store.connect()
    try:
        prof = matching.Profile(con)
        q = matching.ranked(store.load(con, "new", description=False), prof)
        left = len(q)
        q = q[~q["job_url"].isin(exclude)].head(limit)
        return {"left": left, "jobs": [_job(con, row, prof) for _, row in q.iterrows()]}
    finally:
        con.close()


@router.post("/swipe")
async def swipe(request: Request, bg: BackgroundTasks):
    """Record one decision, then report which of the jobs the app holds are no longer new
    (swiped on the web, filed elsewhere) so it can drop them."""
    body = await request.json()
    url, action = str(body.get("url", "")), body.get("action")
    held = [str(u) for u in (body.get("held") or [])[:MAX_HELD]]
    if action != "undo" and action not in ACTIONS:
        return JSONResponse({"error": "bad action"}, 400)
    con = store.connect()
    try:
        if action == "undo":
            store.set_status(con, url, "new")
        else:
            store.set_status(con, url, ACTIONS[action], swipe=True)
            if action == "save":
                bg.add_task(sinks.notify, "saved", store.get_job(con, url))
        fresh = set()
        if held:
            marks = ",".join("?" * len(held))
            fresh = {r[0] for r in con.execute(f"SELECT job_url FROM jobs WHERE status='new' AND job_url IN ({marks})", held)}
        return {"ok": True, "left": store.counts(con)["new"], "stale": [u for u in held if u not in fresh]}
    finally:
        con.close()
