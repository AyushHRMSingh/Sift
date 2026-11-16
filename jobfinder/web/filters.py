"""Template filters, also used by the JSON API."""
import re
from urllib.parse import urlparse


def safe_url(u):
    return u if urlparse(u or "").scheme in ("http", "https") else "#"


def plain(text):
    """Scraped descriptions carry markdown; show them as clean text."""
    text = re.sub(r"\*\*|__|\\", "", text or "")
    return re.sub(r"(?m)^(\s*)[*+-]\s+", r"\1- ", text)


def money(v):
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)
