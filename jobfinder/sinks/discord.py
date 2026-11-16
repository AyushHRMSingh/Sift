"""Discord webhook: a twice-daily digest of what is waiting. Configure with DISCORD_WEBHOOK_URL in .env."""
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

    def push_reminder(self, counts: dict) -> None:
        lines = []
        if counts["saved"]:
            lines.append(f"{counts['saved']} to apply: {settings.PUBLIC_URL}/saved" if settings.PUBLIC_URL else f"{counts['saved']} to apply")
        if counts["queue"]:
            lines.append(f"{counts['queue']} in the swipe queue: {settings.PUBLIC_URL}/" if settings.PUBLIC_URL else f"{counts['queue']} in the swipe queue")
        _post(self.url, {"content": "\n".join(lines), "allowed_mentions": {"parse": []}})

    def test(self) -> None:
        _post(self.url, {"content": "JobSpy test message: alerts are connected.", "allowed_mentions": {"parse": []}})
