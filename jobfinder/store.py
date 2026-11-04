import json
import re
import sqlite3
from datetime import datetime, timezone

import pandas as pd
from pathlib import Path

from . import settings
from .experience import job_years
from .skills import extract

DB_PATH = settings.DATA_DIR / "jobs.db"
COLS = ["job_url", "title", "company", "location", "site", "date_posted", "job_type", "job_level",
        "min_amount", "max_amount", "currency", "description", "search_city", "search_term"]
STATUSES = ("new", "saved", "research", "applied", "rejected")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs (
    {', '.join(f'{c} TEXT' for c in COLS if c != 'job_url')},
    job_url TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL, finished TEXT, added INTEGER DEFAULT 0, seen INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id=1), resume_text TEXT, skills TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""
# columns added after the first version; ALTERed in if missing
MIGRATIONS = {"jobs": {"skills": "TEXT", "exp_min": "REAL", "exp_max": "REAL", "swiped_at": "TEXT", "notified": "TEXT", "dupkey": "TEXT"},
              "scans": {"errors": "TEXT"}}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _migrate_legacy() -> None:
    legacy = settings.ROOT / "jobs.db"
    if legacy.exists() and not DB_PATH.exists():
        legacy.rename(DB_PATH)


def connect() -> sqlite3.Connection:
    _migrate_legacy()
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols.items():
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dupkey ON jobs(dupkey)")
    con.commit()
    return con


def dupkey(company, title, city) -> str:
    """Same job posted on several boards shares company + title + city."""
    norm = lambda v: re.sub(r"[^a-z0-9]+", "", (v or "").lower())
    return f"{norm(company)}|{norm(title)}|{norm(city)}"


def _derived(title, description) -> tuple[str, float | None, float | None]:
    lo, hi = job_years(f"{title or ''} {description or ''}")
    return json.dumps(sorted(extract(f"{title or ''} \n {description or ''}"))), lo, hi


def backfill(con: sqlite3.Connection) -> int:
    """Compute skills/experience for new rows, and recompute everything when the skill dictionary changed."""
    import hashlib
    from .skills import SKILLS
    version = hashlib.md5(json.dumps(SKILLS, sort_keys=True).encode()).hexdigest()
    if get_kv(con, "skills_version") != version:
        con.execute("UPDATE jobs SET skills=NULL")
        set_kv(con, "skills_version", version)
    for url, company, title, city in con.execute(
            "SELECT job_url, company, title, search_city FROM jobs WHERE dupkey IS NULL").fetchall():
        con.execute("UPDATE jobs SET dupkey=? WHERE job_url=?", (dupkey(company, title, city), url))
    rows = con.execute("SELECT job_url, title, description FROM jobs WHERE skills IS NULL").fetchall()
    for url, title, desc in rows:
        con.execute("UPDATE jobs SET skills=?, exp_min=?, exp_max=? WHERE job_url=?", (*_derived(title, desc), url))
    con.commit()
    return len(rows)


def upsert(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Insert new jobs, refresh last_seen on known ones. Returns number of new jobs."""
    ts, added = now(), 0
    for rec in df.reindex(columns=COLS).astype(object).where(df.notna(), None).to_dict("records"):
        if not rec["job_url"]:
            continue
        rec = {k: (None if v is None else str(v)) for k, v in rec.items()}
        cur = con.execute("UPDATE jobs SET last_seen=? WHERE job_url=?", (ts, rec["job_url"]))
        if cur.rowcount == 0:
            key = dupkey(rec["company"], rec["title"], rec["search_city"])
            twin = con.execute("SELECT job_url, LENGTH(COALESCE(description,'')) FROM jobs WHERE dupkey=?", (key,)).fetchone()
            if twin:  # same job from another board: keep one row, prefer the fuller description
                con.execute("UPDATE jobs SET last_seen=? WHERE job_url=?", (ts, twin[0]))
                if len(rec.get("description") or "") > twin[1]:
                    sk, lo, hi = _derived(rec["title"], rec["description"])
                    con.execute("UPDATE jobs SET description=?, skills=?, exp_min=?, exp_max=? WHERE job_url=?",
                                (rec["description"], sk, lo, hi, twin[0]))
                continue
            sk, lo, hi = _derived(rec["title"], rec["description"])
            con.execute(f"INSERT INTO jobs ({', '.join(COLS)}, first_seen, last_seen, skills, exp_min, exp_max, dupkey) "
                        f"VALUES ({', '.join('?' * len(COLS))}, ?, ?, ?, ?, ?, ?)", [*rec.values(), ts, ts, sk, lo, hi, key])
            added += 1
        elif rec.get("description"):
            had = con.execute("SELECT COALESCE(description,'') FROM jobs WHERE job_url=?", (rec["job_url"],)).fetchone()[0]
            if not had:
                sk, lo, hi = _derived(rec["title"], rec["description"])
                con.execute("UPDATE jobs SET description=?, skills=?, exp_min=?, exp_max=? WHERE job_url=?",
                            (rec["description"], sk, lo, hi, rec["job_url"]))
    con.commit()
    return added


def load(con: sqlite3.Connection, status=None, description: bool = True) -> pd.DataFrame:
    """Jobs as a DataFrame with `skills` as a list. Skip descriptions when ranking large queues."""
    cols = "*" if description else ", ".join(c for c in COLS if c != "description") + \
        ", first_seen, last_seen, status, skills, exp_min, exp_max, swiped_at, notified, dupkey"
    where, args = "", []
    if status:
        statuses = [status] if isinstance(status, str) else list(status)
        where = f"WHERE status IN ({', '.join('?' * len(statuses))})"
        args = statuses
    df = pd.read_sql(f"SELECT {cols} FROM jobs {where}", con, params=args)
    df["date_posted"] = pd.to_datetime(df["date_posted"], format="mixed", errors="coerce")
    df["skills"] = df["skills"].map(lambda s: json.loads(s) if s else [])
    return df


def get_job(con: sqlite3.Connection, url: str) -> dict | None:
    cur = con.execute("SELECT * FROM jobs WHERE job_url=?", (url,))
    row = cur.fetchone()
    if not row:
        return None
    job = dict(zip([d[0] for d in cur.description], row))
    job["skills"] = json.loads(job["skills"]) if job.get("skills") else []
    return job


def set_status(con: sqlite3.Connection, url: str, status: str, swipe: bool = False) -> None:
    if status not in STATUSES:
        raise ValueError(status)
    con.execute("UPDATE jobs SET status=?, swiped_at=? WHERE job_url=?", (status, now() if swipe else None, url))
    con.commit()


def mark_notified(con: sqlite3.Connection, urls: list[str]) -> None:
    con.executemany("UPDATE jobs SET notified=? WHERE job_url=?", [(now(), u) for u in urls])
    con.commit()


def undo_last_swipe(con: sqlite3.Connection) -> str | None:
    row = con.execute("SELECT job_url FROM jobs WHERE swiped_at IS NOT NULL ORDER BY swiped_at DESC, rowid DESC LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE jobs SET status='new', swiped_at=NULL WHERE job_url=?", (row[0],))
        con.commit()
    return row[0] if row else None


def counts(con: sqlite3.Connection) -> dict:
    out = {s: 0 for s in STATUSES}
    out.update(dict(con.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")))
    return out


def last_scan(con: sqlite3.Connection) -> dict | None:
    cur = con.execute("SELECT id, started, finished, added, seen, errors FROM scans ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row)) if row else None


def recent_scans(con: sqlite3.Connection, n: int = 10) -> list[dict]:
    cur = con.execute("SELECT id, started, finished, added, seen, errors FROM scans ORDER BY id DESC LIMIT ?", (n,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def save_profile(con: sqlite3.Connection, resume_text: str, skills: list[str]) -> None:
    con.execute("INSERT OR REPLACE INTO profile (id, resume_text, skills) VALUES (1, ?, ?)",
                (resume_text, json.dumps(sorted(skills))))
    con.commit()


def load_profile(con: sqlite3.Connection) -> tuple[str, list[str]]:
    row = con.execute("SELECT resume_text, skills FROM profile WHERE id=1").fetchone()
    return (row[0], json.loads(row[1])) if row else ("", [])


def get_kv(con: sqlite3.Connection, key: str, default=None):
    row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_kv(con: sqlite3.Connection, key: str, value) -> None:
    con.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()


_STATUS_RANK = {"applied": 0, "saved": 1, "rejected": 2, "new": 3}


def merge_duplicates(con: sqlite3.Connection) -> int:
    """One-off cleanup of existing twins. Keeps the row you acted on, else the one with the fullest description."""
    groups = con.execute("SELECT dupkey FROM jobs WHERE dupkey IS NOT NULL GROUP BY dupkey HAVING COUNT(*) > 1").fetchall()
    if not groups:
        return 0
    backup(tag="pre-dedupe")
    removed = 0
    for (key,) in groups:
        rows = con.execute("SELECT job_url, status, LENGTH(COALESCE(description,'')), first_seen FROM jobs WHERE dupkey=?", (key,)).fetchall()
        rows.sort(key=lambda r: (_STATUS_RANK.get(r[1], 9), -r[2], r[3]))
        for r in rows[1:]:
            con.execute("DELETE FROM jobs WHERE job_url=?", (r[0],))
            removed += 1
    con.commit()
    return removed


def backup(keep: int = 7, tag: str | None = None) -> "Path":
    """Copy the database to data/backups/. Daily backups are rotated; tagged ones are kept."""
    folder = settings.DATA_DIR / "backups"
    folder.mkdir(exist_ok=True)
    dest = folder / (f"jobs-{tag}.db" if tag else f"jobs-{datetime.now(timezone.utc):%Y%m%d}.db")
    if not tag and dest.exists():
        return dest
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    dest.chmod(0o600)
    if not tag:
        for old in sorted(folder.glob("jobs-2*.db"))[:-keep]:
            old.unlink()
    return dest
