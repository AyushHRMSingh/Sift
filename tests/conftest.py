import os
import tempfile

# Isolate all state before any jobfinder module reads its settings.
_DATA = tempfile.mkdtemp(prefix="jobfinder-test-")
os.environ.update(DATA_DIR=_DATA, APP_PASSWORD="test-pass", APP_USER="admin", SECURE_COOKIES="0",
                  SINKS="", DISCORD_WEBHOOK_URL="")
os.environ.pop("SCRAPE_PROXIES", None)

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from jobfinder import store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    for p in Path(_DATA).glob("jobs.db*"):
        p.unlink()
    shutil.rmtree(Path(_DATA) / "backups", ignore_errors=True)
    yield


@pytest.fixture
def con():
    c = store.connect()
    yield c
    c.close()


def make_jobs(*rows):
    """DataFrame shaped like scrape output. Each row: dict overriding the defaults."""
    base = {"title": "Python Developer", "company": "Acme", "location": "Pune, India", "site": "linkedin",
            "date_posted": pd.Timestamp.now().normalize(), "description": "We use Python and Django. " * 5,
            "search_city": "Pune", "search_term": "python developer", "min_amount": None, "max_amount": None,
            "currency": None, "job_type": None, "job_level": None}
    out = []
    for i, r in enumerate(rows):
        out.append({**base, "job_url": f"https://example.com/job/{i}", **r})
    return pd.DataFrame(out)
