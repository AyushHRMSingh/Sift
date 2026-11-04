import pandas as pd

from jobfinder import matching, skills, store
from jobfinder.analysis import analyze
from jobfinder.scan import clean
from tests.conftest import make_jobs


def test_clean_filters_senior_non_dev_and_wrong_city():
    df = make_jobs({"title": "Python Developer"}, {"title": "Senior Python Developer"},
                   {"title": "Sales Executive"}, {"title": "SDE 2 Backend"}, {"location": "Chennai, India"})
    out = clean(df, "Pune", "python developer")
    assert out["title"].tolist() == ["Python Developer"]


def test_match_floor_prevents_one_skill_hundred_percent():
    df = pd.DataFrame({"skills": [["Python"], ["Python", "SQL", "AWS", "Git", "Docker"]],
                       "exp_min": [None, None]})
    out = skills.add_match(df, ["Python"])
    assert out["match_%"].tolist() == [20, 20]
    assert out["missing"][1] == ["SQL", "AWS", "Git", "Docker"]


def test_experience_gate_allows_none_and_one_year_of_slack():
    df = pd.DataFrame({"skills": [["Python"]] * 3, "exp_min": [None, 2.0, 4.0]})
    assert skills.add_match(df, ["Python"], years=1.0)["exp_ok"].tolist() == [True, True, False]


def test_ranked_hides_stale_and_too_senior_and_sorts_by_match(con):
    old = pd.Timestamp.now() - pd.Timedelta(days=90)
    store.upsert(con, make_jobs({"title": "Python Developer"}, {"title": "Java Developer", "description": "Java Spring Boot AWS Docker Kubernetes"},
                                {"title": "Old Python Dev", "date_posted": old}, {"title": "Python Dev 5+ years experience"}))
    store.save_profile(con, "", ["Python", "Django"])
    prof = matching.Profile(con)
    prof.years = 1.0
    titles = matching.ranked(store.load(con, "new", description=False), prof)["title"].tolist()
    assert "Old Python Dev" not in titles and "Python Dev 5+ years experience" not in titles
    assert titles[0] == "Python Developer"


def test_analysis_handles_small_data_without_crashing(con):
    store.upsert(con, make_jobs({}, {"title": "Backend Developer"}))
    a = analyze(store.load(con), ["Python"], 1.0)
    assert a["n"] == 2 and a["trend_note"] and a["demand"] and a["learn"] is not None


def test_analysis_empty():
    assert analyze(pd.DataFrame(), [], None) == {"n": 0}


def test_ranked_copes_with_mixed_timestamp_formats_in_first_seen(con):
    """Older rows have second precision, newer ones microseconds; both must parse, and age must still be judged."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    store.upsert(con, make_jobs(*[{"title": t, "date_posted": None} for t in ("Recent Seconds", "Recent Micro", "Old Seconds")]))
    for i, stamp in enumerate([now.isoformat(timespec="seconds"), now.isoformat(timespec="microseconds"),
                               (now - timedelta(days=90)).isoformat(timespec="seconds")]):
        con.execute("UPDATE jobs SET first_seen=? WHERE job_url=?", (stamp, f"https://example.com/job/{i}"))
    con.commit()
    store.save_profile(con, "", ["Python"])
    out = matching.ranked(store.load(con, "new", description=False), matching.Profile(con))
    assert sorted(out["title"]) == ["Recent Micro", "Recent Seconds"]
