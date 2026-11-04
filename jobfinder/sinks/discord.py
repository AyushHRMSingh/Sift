"""Discord webhook alerts: new strong matches after each scan. Configure with DISCORD_WEBHOOK_URL in .env."""
import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .. import settings
from . import Sink, register

log = logging.getLogger("jobfinder.discord")
HOSTS = {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
MAX_EMBEDS = 10  # Discord's per-message limit


def _post(url: str, body: dict) -> None:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "JobSpy/1.0"})
    for attempt in range(2):
        try:
            urllib.request.urlopen(req, timeout=15).read()
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:  # rate limited: wait as told, retry once
                time.sleep(min(float(json.loads(e.read() or b"{}").get("retry_after", 2)), 10))
                continue
            raise


def embed(job: dict) -> dict:
    facts = [job.get("company") or "", job.get("search_city") or "", f"{int(job['match_%'])}% match"]
    if job.get("exp_min") == job.get("exp_min") and job.get("exp_min") is not None:
        facts.append(f"{job['exp_min']:g}-{job['exp_max']:g} yrs")
    out = {"title": (job.get("title") or "Job")[:250], "url": job["job_url"],
           "description": " | ".join(f for f in facts if f)}
    if job.get("missing"):
        out["footer"] = {"text": ("Missing: " + ", ".join(job["missing"]))[:200]}
    return out


@register
class DiscordSink(Sink):
    name = "discord"

    def __init__(self):
        host = urlparse(settings.DISCORD_WEBHOOK_URL).hostname or ""
        if host not in HOSTS or "/api/webhooks/" not in settings.DISCORD_WEBHOOK_URL:
            raise ValueError("DISCORD_WEBHOOK_URL is not a Discord webhook URL")
        self.url = settings.DISCORD_WEBHOOK_URL

    def push_saved(self, job: dict) -> None:
        pass  # alerts are about new matches, not your own actions

    def push_scan(self, jobs: list[dict]) -> None:
        head = jobs[:MAX_EMBEDS]
        text = f"{len(jobs)} new job{'s' if len(jobs) != 1 else ''} at {settings.DISCORD_MIN_MATCH}%+ match"
        if len(jobs) > len(head):
            text += f" (showing the top {len(head)})"
        if settings.PUBLIC_URL:
            text += f"\n{settings.PUBLIC_URL}/"
        _post(self.url, {"content": text, "embeds": [embed(j) for j in head], "allowed_mentions": {"parse": []}})

    def push_reminder(self, pending: int) -> None:
        text = f"{pending} application{'s' if pending != 1 else ''} pending in your queue."
        if settings.PUBLIC_URL:
            text += f"\n{settings.PUBLIC_URL}/saved"
        _post(self.url, {"content": text, "allowed_mentions": {"parse": []}})

    def test(self) -> None:
        _post(self.url, {"content": "JobSpy test message: alerts are connected.", "allowed_mentions": {"parse": []}})
