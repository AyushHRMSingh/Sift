"""Pluggable destinations for saved jobs (Google Sheets, webhooks, ...).

To add one: subclass `Sink`, implement `push_saved`, decorate with `@register`, and enable it with
the env var SINKS=name1,name2. Sinks run in the background after you save a job; a failing sink
is logged and never breaks the app.
"""
import logging
import os
from abc import ABC, abstractmethod

from .. import settings  # noqa: E402

log = logging.getLogger("jobfinder.sinks")
REGISTRY: dict[str, type["Sink"]] = {}


class Sink(ABC):
    name: str = ""

    @abstractmethod
    def push_saved(self, job: dict) -> None:
        """Called once when a job moves to 'saved'. `job` is a plain dict of the stored row."""

    def push_status(self, job: dict) -> None:
        """Called when a saved job changes status (applied/rejected). Optional."""

    def push_reminder(self, pending: int) -> None:
        """Called at the reminder times with the number of jobs waiting in 'saved'. Optional."""

    def push_scan(self, jobs: list[dict]) -> None:
        """Called after a scan with the new strong matches, best first. Optional."""


def register(cls: type[Sink]) -> type[Sink]:
    REGISTRY[cls.name] = cls
    return cls


def active_sinks() -> list[Sink]:
    out = []
    names = [n.strip() for n in os.environ.get("SINKS", "").split(",")]
    if settings.DISCORD_WEBHOOK_URL:
        names.append("discord")
    for name in dict.fromkeys(filter(None, names)):
        if name not in REGISTRY:
            log.warning("unknown sink %r (known: %s)", name, ", ".join(REGISTRY))
            continue
        try:
            out.append(REGISTRY[name]())
        except Exception as e:
            log.warning("sink %s disabled: %s", name, e)
    return out


def notify(event: str, payload) -> None:
    for sink in active_sinks():
        try:
            getattr(sink, f"push_{event}")(payload)
        except Exception:
            log.exception("sink %s failed on %s", sink.name, event)


from . import discord, jsonl, sheets  # noqa: E402,F401  (register built-in sinks)
