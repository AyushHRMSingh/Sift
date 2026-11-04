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


def test_alerts_strong_matches_once_and_caps_embeds(con, hook):
    strong = "Python Django SQL Git Docker"
    store.upsert(con, make_jobs(*[{"title": f"Python Developer {i}", "company": f"Co{i}", "description": strong * 3} for i in range(12)],
                                {"title": "Java Developer", "company": "Weak", "description": "Java Spring AWS Docker Kubernetes Kafka"}))
    store.save_profile(con, "", ["Python", "Django", "SQL", "Git"])
    assert sinks.active_sinks()
    assert scheduler.alert_new_matches(con) == 12
    msg = hook[0]
    assert len(msg["embeds"]) == 10 and "12 new jobs" in msg["content"] and "showing the top 10" in msg["content"]
    assert msg["allowed_mentions"] == {"parse": []} and msg["embeds"][0]["url"].startswith("https://example.com/job/")
    assert scheduler.alert_new_matches(con) == 0 and len(hook) == 1  # never repeats


def test_no_alert_without_profile(con, hook):
    store.upsert(con, make_jobs({"description": "Python Django SQL Git Docker " * 3}))
    assert scheduler.alert_new_matches(con) == 0 and not hook


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


def test_reminder_sends_count_once_and_stays_quiet_when_empty(con, hook, monkeypatch):
    texts = []
    monkeypatch.setattr(discord, "_post", lambda url, body: texts.append(body["content"]))
    monkeypatch.setattr(settings, "REMINDER_TIMES", ["18:30"])
    assert scheduler.send_reminders(con, at(18, 30)) == []  # nothing saved yet
    assert texts == []
    store.upsert(con, make_jobs({}, {"title": "Backend Developer"}))
    store.set_status(con, "https://example.com/job/0", "saved")
    store.set_status(con, "https://example.com/job/1", "saved")
    assert scheduler.send_reminders(con, at(18, 31)) == []  # slot already consumed today
    assert scheduler.send_reminders(con, datetime(2026, 11, 6, 18, 31, tzinfo=IST)) == ["18:30"]
    assert texts[0].startswith("2 applications pending in your queue.") and texts[0].endswith("/saved")
    assert scheduler.send_reminders(con, datetime(2026, 11, 6, 18, 32, tzinfo=IST)) == [] and len(texts) == 1
