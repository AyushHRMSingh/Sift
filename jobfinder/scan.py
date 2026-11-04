import time
from typing import Callable

import pandas as pd
from jobspy import scrape_jobs

from . import settings, store
from .config import DEV_RE, SENIOR_RE, city_matches


def clean(df: pd.DataFrame, city: str, term: str) -> pd.DataFrame:
    """Local relevance filter: right city, dev title, not senior."""
    if df is None or df.empty:
        return pd.DataFrame()
    t = df["title"].fillna("")
    df = df[t.str.contains(DEV_RE) & ~t.str.contains(SENIOR_RE)]
    df = df[df["location"].map(lambda l: city_matches(l, city))].copy()
    df["search_city"], df["search_term"] = city, term
    return df


def run_scan(queries, cities, sites, n=30, days=7, full=True, pause=2.0,
             progress: Callable[[str, float], None] | None = None) -> dict:
    """Scrape every (query, city) pair and store results. One failure never aborts the scan."""
    con = store.connect()
    scan_id = con.execute("INSERT INTO scans (started) VALUES (?)", (store.now(),)).lastrowid
    con.commit()
    jobs = [(q, c) for q in queries for c in cities]
    added = seen = 0
    errors = []
    for i, (term, city) in enumerate(jobs):
        if progress:
            progress(f"{term} · {city}", i / len(jobs))
        try:
            df = scrape_jobs(site_name=list(sites), search_term=term,
                             google_search_term=f"{term} jobs near {city}, India since last week",
                             location=f"{city}, India", results_wanted=n, hours_old=max(1, int(days * 24)),
                             country_indeed="India", fetch_description=full, verbose=0,
                             proxies=settings.PROXIES or None)
            df = clean(df, city, term)
            seen += len(df)
            added += store.upsert(con, df) if len(df) else 0
        except Exception as e:
            errors.append(f"{term} · {city}: {e}")
        time.sleep(pause)
    con.execute("UPDATE scans SET finished=?, added=?, seen=?, errors=? WHERE id=?",
                (store.now(), added, seen, "\n".join(errors) or None, scan_id))
    con.commit()
    con.close()
    if progress:
        progress("done", 1.0)
    return {"added": added, "seen": seen, "errors": errors}
