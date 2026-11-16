"""Profile-aware views over the job store."""
import pandas as pd

from . import settings, skills, store
from .experience import parse_experience


class Profile:
    def __init__(self, con):
        self.resume_text, self.skills = store.load_profile(con)
        self.experience = parse_experience(self.resume_text) if self.resume_text else None
        override = store.get_kv(con, "years")
        parsed = self.experience["years"] if self.experience else None
        self.years = override if override is not None else parsed


def posted_day(df: pd.DataFrame) -> pd.Series:
    """Day a job went up: the board's posted date, else the day we first saw it."""
    seen = pd.to_datetime(df["first_seen"], format="ISO8601", utc=True).dt.tz_localize(None)
    return df["date_posted"].astype("datetime64[ns]").fillna(seen.astype("datetime64[ns]")).dt.normalize()


def ranked(df: pd.DataFrame, profile: Profile, hide_senior_exp: bool = True) -> pd.DataFrame:
    """Freshest first, best match within a day: time matters more than fit."""
    if len(df):
        df = df.assign(_day=posted_day(df))
        if settings.STALE_DAYS:
            df = df[df["_day"] >= pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=settings.STALE_DAYS)]
    else:
        df = df.assign(_day=pd.Series(dtype="datetime64[ns]"))
    df = skills.add_match(df, profile.skills, profile.years)
    if hide_senior_exp and profile.years is not None:
        df = df[df["exp_ok"]]
    return df.sort_values(["_day", "match_%"], ascending=False, na_position="last").drop(columns="_day")
