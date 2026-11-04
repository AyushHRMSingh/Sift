"""Background scanner: wakes every minute, runs a scan when one is due."""
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import matching, settings, sinks, store
from ..scan import run_scan

log = logging.getLogger("jobfinder.scheduler")
_lock = threading.Lock()
state = {"running": False, "message": "idle", "progress": 0.0}


def alert_new_matches(con) -> int:
    """Push unseen strong matches to the sinks (Discord), once per job."""
    prof = matching.Profile(con)
    if not prof.skills:
        return 0
    df = store.load(con, "new", description=False)
    df = matching.ranked(df[df["notified"].isna()], prof)
    strong = df[df["match_%"] >= settings.DISCORD_MIN_MATCH]
    if strong.empty:
        return 0
    sinks.notify("scan", strong.to_dict("records"))
    store.mark_notified(con, strong["job_url"].tolist())
    return len(strong)


def get_config(con) -> dict:
    return {**settings.DEFAULT_SCAN, **(store.get_kv(con, "scan_config", {}) or {})}


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def run_now(manual: bool = False) -> bool:
    """Run one scan synchronously. Returns False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False
    con = store.connect()
    try:
        cfg = get_config(con)
        last = store.last_scan(con)
        days = cfg["days"]
        if not manual and last and last["finished"]:
            hours = (datetime.now(timezone.utc) - _parse(last["finished"])).total_seconds() / 3600
            days = min(days, max(hours + 2, 6) / 24)  # only look back since the last scan, plus slack
        state.update(running=True, message="starting", progress=0.0)
        res = run_scan(cfg["queries"], cfg["cities"], cfg["sites"], cfg["results"], days,
                       cfg["full_descriptions"],
                       progress=lambda msg, f: state.update(message=msg, progress=f))
        log.info("scan done: %s", {k: v for k, v in res.items() if k != "errors"})
        if sinks.active_sinks():
            log.info("alerted on %d jobs", alert_new_matches(con))
        return True
    except Exception:
        log.exception("scan crashed")
        return True
    finally:
        state.update(running=False, message="idle", progress=0.0)
        con.close()
        _lock.release()


def due(con) -> bool:
    cfg = get_config(con)
    if not cfg["enabled"]:
        return False
    last = store.last_scan(con)
    if not last or not last["finished"]:
        return not last or (datetime.now(timezone.utc) - _parse(last["started"])).total_seconds() > 4 * 3600
    elapsed = (datetime.now(timezone.utc) - _parse(last["finished"])).total_seconds()
    return elapsed >= cfg["interval_hours"] * 3600


async def loop():
    await asyncio.sleep(10)
    while True:
        try:
            con = store.connect()
            try:
                go = due(con) and not state["running"]
            finally:
                con.close()
            await asyncio.to_thread(store.backup)  # no-op once today's copy exists
            if go:
                await asyncio.to_thread(run_now)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(60)


def due_slots(now: datetime, sent: dict, times: list[str], grace_min: int = 10) -> list[str]:
    """Reminder times that have just passed (within the grace window) and haven't fired today."""
    out = []
    for t in times:
        try:
            h, m = map(int, t.split(":"))
            slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            continue
        if slot <= now < slot + timedelta(minutes=grace_min) and sent.get(t) != now.date().isoformat():
            out.append(t)
    return out


def send_reminders(con, now: datetime) -> list[str]:
    """Send the pending-applications reminder for each due slot. Stays quiet when the queue is empty."""
    sent = store.get_kv(con, "reminders_sent", {}) or {}
    slots = due_slots(now, sent, settings.REMINDER_TIMES)
    if not slots:
        return []
    pending = store.counts(con)["saved"]
    for t in slots:
        sent[t] = now.date().isoformat()
        if pending:
            sinks.notify("reminder", pending)
    store.set_kv(con, "reminders_sent", sent)
    return slots if pending else []


async def reminder_loop():
    """Runs apart from the scan loop so a long scan can't make it miss a slot."""
    try:
        tz = ZoneInfo(settings.REMINDER_TZ)
    except Exception:
        log.error("bad REMINDER_TZ %r; reminders disabled", settings.REMINDER_TZ)
        return
    while True:
        try:
            if sinks.active_sinks():
                con = store.connect()
                try:
                    send_reminders(con, datetime.now(tz))
                finally:
                    con.close()
        except Exception:
            log.exception("reminder tick failed")
        await asyncio.sleep(30)
