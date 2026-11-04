import json

from jobfinder import store
from tests.conftest import make_jobs


def test_upsert_inserts_once_and_stores_derived_fields(con):
    df = make_jobs({"title": "Python Developer 0-2 years"})
    assert store.upsert(con, df) == 1
    assert store.upsert(con, df) == 0  # same url: no new row
    job = store.get_job(con, "https://example.com/job/0")
    assert "Python" in job["skills"] and job["exp_max"] == 2.0 and job["status"] == "new"


def test_cross_board_duplicate_merges_and_keeps_fuller_description(con):
    short = make_jobs({"site": "naukri", "description": "short"})
    full = make_jobs({"site": "linkedin", "description": "Long description with Python and Django. " * 10})
    full["job_url"] = "https://other.example.com/x"
    assert store.upsert(con, short) == 1
    assert store.upsert(con, full) == 0
    rows = con.execute("SELECT job_url, description FROM jobs").fetchall()
    assert len(rows) == 1 and "Long description" in rows[0][1]


def test_same_title_different_city_is_not_a_duplicate(con):
    df = make_jobs({}, {"search_city": "Mumbai"})
    assert store.upsert(con, df) == 2


def test_status_and_undo_last_swipe(con):
    store.upsert(con, make_jobs({}, {"title": "Other Dev"}))
    store.set_status(con, "https://example.com/job/0", "saved", swipe=True)
    store.set_status(con, "https://example.com/job/1", "rejected", swipe=True)
    assert store.undo_last_swipe(con) == "https://example.com/job/1"
    assert store.counts(con) == {"new": 1, "saved": 1, "research": 0, "applied": 0, "rejected": 0}
    assert store.undo_last_swipe(con) == "https://example.com/job/0"
    assert store.undo_last_swipe(con) is None


def test_status_changes_outside_swiping_are_not_undoable(con):
    store.upsert(con, make_jobs({}))
    store.set_status(con, "https://example.com/job/0", "applied")
    assert store.undo_last_swipe(con) is None


def test_invalid_status_rejected(con):
    store.upsert(con, make_jobs({}))
    try:
        store.set_status(con, "https://example.com/job/0", "bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_merge_duplicates_keeps_acted_on_row(con):
    for url, status, desc in [("a", "new", "x" * 500), ("b", "saved", "y"), ("c", "new", "z" * 10)]:
        con.execute("INSERT INTO jobs (job_url, title, company, search_city, description, dupkey, first_seen, last_seen, status) "
                    "VALUES (?, 't', 'c', 'Pune', ?, 'k', '2026-01-01', '2026-01-01', ?)", (url, desc, status))
    con.commit()
    assert store.merge_duplicates(con) == 2
    assert [r[0] for r in con.execute("SELECT job_url FROM jobs")] == ["b"]
    assert (store.settings.DATA_DIR / "backups" / "jobs-pre-dedupe.db").exists()


def test_backfill_recomputes_when_dictionary_changes(con):
    store.upsert(con, make_jobs({}))
    store.backfill(con)
    store.set_kv(con, "skills_version", "stale")
    con.execute("UPDATE jobs SET skills='[]'")
    assert store.backfill(con) == 1
    assert "Python" in json.loads(con.execute("SELECT skills FROM jobs").fetchone()[0])


def test_backup_is_daily_and_rotates(con):
    store.upsert(con, make_jobs({}))
    folder = store.settings.DATA_DIR / "backups"
    folder.mkdir(exist_ok=True)
    for day in range(1, 10):
        (folder / f"jobs-202001{day:02d}.db").write_bytes(b"old")
    today = store.backup(keep=3)
    assert today.exists() and store.backup(keep=3) == today  # second call is a no-op
    assert len(list(folder.glob("jobs-2*.db"))) == 3 and today in folder.glob("jobs-2*.db")


def test_profile_and_kv_roundtrip(con):
    store.save_profile(con, "resume text", ["Python", "SQL"])
    assert store.load_profile(con) == ("resume text", ["Python", "SQL"])
    store.set_kv(con, "years", 1.5)
    assert store.get_kv(con, "years") == 1.5 and store.get_kv(con, "missing", "d") == "d"
