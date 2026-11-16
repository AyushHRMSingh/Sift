from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jobfinder import settings, sinks, store
from jobfinder.sinks import discord
from jobfinder.web import scheduler
from tests.conftest import make_jobs


@pytest.fixture
def hook(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://jobs.example.com")
    monkeypatch.setattr(discord, "_post", lambda url, body: sent.append(body))
    return sent


@pytest.mark.parametrize("bad", ["https://evil.com/api/webhooks/1/x", "http://169.254.169.254/api/webhooks/1", "https://discord.com/other", ""])
def test_rejects_non_discord_urls(monkeypatch, bad):
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", bad)
    with pytest.raises(ValueError):
        discord.DiscordSink()


IST = ZoneInfo("Asia/Kolkata")


def at(h, m):
    return datetime(2026, 11, 5, h, m, tzinfo=IST)


def test_due_slots_fire_once_inside_grace_window():
    times = ["18:30", "20:30"]
    assert scheduler.due_slots(at(18, 29), {}, times) == []
    assert scheduler.due_slots(at(18, 30), {}, times) == ["18:30"]
    assert scheduler.due_slots(at(18, 39), {}, times) == ["18:30"]
    assert scheduler.due_slots(at(18, 45), {}, times) == []  # too late, skipped
    assert scheduler.due_slots(at(18, 31), {"18:30": "2026-11-05"}, times) == []  # already sent today
    assert scheduler.due_slots(at(18, 31), {"18:30": "2026-11-04"}, times) == ["18:30"]  # sent yesterday only
    assert scheduler.due_slots(at(20, 31), {}, ["bogus", "20:30"]) == ["20:30"]


def test_digest_reports_to_apply_and_queue_once_per_slot_and_stays_quiet_when_empty(con, hook, monkeypatch):
    texts = []
    monkeypatch.setattr(discord, "_post", lambda url, body: texts.append(body["content"]))
    monkeypatch.setattr(settings, "REMINDER_TIMES", ["18:30"])
    assert scheduler.send_reminders(con, at(18, 30)) == []  # nothing anywhere yet
    assert texts == []
    store.upsert(con, make_jobs({"company": "A"}, {"company": "B", "title": "Backend Developer"}, {"company": "C", "title": "Java Developer"}))
    urls = store.load(con, "new", description=False)["job_url"].tolist()
    store.set_status(con, urls[0], "saved")
    store.set_status(con, urls[1], "saved")
    assert scheduler.send_reminders(con, at(18, 31)) == []  # slot already consumed today
    assert scheduler.send_reminders(con, datetime(2026, 11, 6, 18, 31, tzinfo=IST)) == ["18:30"]
    assert texts[0] == "2 to apply: https://jobs.example.com/saved\n1 in the swipe queue: https://jobs.example.com/"
    assert scheduler.send_reminders(con, datetime(2026, 11, 6, 18, 32, tzinfo=IST)) == [] and len(texts) == 1


def test_scan_never_sends_per_job_alerts(con, hook, monkeypatch):
    store.upsert(con, make_jobs({"job_url": "https://x/1"}))
    store.save_profile(con, "", ["Python"])
    monkeypatch.setattr(scheduler, "run_scan", lambda *a, **k: {})
    scheduler.run_now()
    store.upsert(con, make_jobs({"job_url": "https://x/2", "company": "Other"}))
    scheduler.run_now()
    assert hook == []
