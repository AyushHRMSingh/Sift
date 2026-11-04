import json

from .. import settings
from . import Sink, register


@register
class JsonlSink(Sink):
    """Appends saved jobs to data/saved.jsonl. Mostly a working reference for writing sinks."""
    name = "jsonl"

    def push_saved(self, job: dict) -> None:
        keep = ("job_url", "title", "company", "location", "search_city", "date_posted", "skills")
        with open(settings.DATA_DIR / "saved.jsonl", "a") as f:
            f.write(json.dumps({k: job.get(k) for k in keep}, default=str) + "\n")
