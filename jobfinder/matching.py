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


def ranked(df: pd.DataFrame, profile: Profile, hide_senior_exp: bool = True) -> pd.DataFrame:
    if settings.STALE_DAYS and len(df):  # posted date, or first seen when the board gave none
        age = df["date_posted"].fillna(pd.to_datetime(df["first_seen"], utc=True).dt.tz_localize(None))
        df = df[age >= pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(days=settings.STALE_DAYS)]
    df = skills.add_match(df, profile.skills, profile.years)
    if hide_senior_exp and profile.years is not None:
        df = df[df["exp_ok"]]
    return df.sort_values(["match_%", "date_posted"], ascending=False, na_position="last")
