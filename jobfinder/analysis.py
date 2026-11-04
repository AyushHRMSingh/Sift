"""Market analysis over stored jobs: demand, trends, senior-vs-entry gap, salary, and what to do about it."""
from collections import Counter
from statistics import median

import pandas as pd

STRONG = 60          # match % that counts as a real fit
MIN_TREND_JOBS = 30  # jobs needed in each week before trends are shown
MIN_GROUP = 15       # jobs needed per group for the level comparison
MIN_SALARIES = 15


def _share(rows: list[list[str]]) -> dict[str, float]:
    c = Counter(s for r in rows for s in set(r))
    n = max(len(rows), 1)
    return {k: v / n for k, v in c.items()}


def _annual_inr(row) -> float | None:
    """Salary figures arrive without a period; INR values under 2 lakh are monthly."""
    try:
        v = float(row["min_amount"])
    except (TypeError, ValueError):
        return None
    if (row.get("currency") or "INR") != "INR":
        return None
    v = v * 12 if v < 200_000 else v
    return v if 100_000 <= v <= 20_000_000 else None


def _match(skills: list[str], have: set[str], bonus: int = 0) -> float:
    return 100 * (len(have & set(skills)) + bonus) / max(len(skills), 5)


def analyze(df: pd.DataFrame, mine: list[str], years: float | None) -> dict:
    have = set(mine)
    df = df[df["skills"].map(bool)].copy() if len(df) else df
    out: dict = {"n": len(df)}
    if df.empty:
        return out
    rows = df.to_dict("records")
    skills_all = [r["skills"] for r in rows]
    out["n_desc"] = int((df["description"].fillna("").str.len() > 50).sum())
    posted = df["date_posted"].dropna()
    out["range"] = (posted.min(), posted.max()) if len(posted) else None
    out["sites"] = df["site"].value_counts().to_dict()

    # demand
    share = _share(skills_all)
    out["demand"] = [{"skill": k, "share": round(v * 100, 1), "have": k in have}
                     for k, v in sorted(share.items(), key=lambda kv: -kv[1])[:20]]

    # trends: last 7 days of postings vs the 7 before
    out["trend_note"] = None
    if len(posted):
        latest = posted.max()
        recent = df[df["date_posted"] > latest - pd.Timedelta(days=7)]
        prior = df[(df["date_posted"] <= latest - pd.Timedelta(days=7)) & (df["date_posted"] > latest - pd.Timedelta(days=14))]
        covered = posted.min() <= latest - pd.Timedelta(days=12)  # both weeks must be mostly in range
        if covered and len(recent) >= MIN_TREND_JOBS and len(prior) >= MIN_TREND_JOBS:
            a, b = _share(recent["skills"].tolist()), _share(prior["skills"].tolist())
            cr, cp = Counter(s for r in recent["skills"] for s in set(r)), Counter(s for r in prior["skills"] for s in set(r))
            moves = [{"skill": k, "now": round(a.get(k, 0) * 100, 1), "before": round(b.get(k, 0) * 100, 1),
                      "change": round((a.get(k, 0) - b.get(k, 0)) * 100, 1)}
                     for k in set(a) | set(b) if cr[k] + cp[k] >= 5]
            moves.sort(key=lambda m: -m["change"])
            out["rising"] = [m for m in moves if m["change"] > 0][:8]
            out["falling"] = [m for m in moves[::-1] if m["change"] < 0][:5]
            out["trend_n"] = (len(recent), len(prior))
        else:
            out["trend_note"] = (f"Trends need about two weeks of postings (30+ per week). Postings so far span "
                                 f"{(latest - posted.min()).days + 1} days. This fills in as scans accumulate.")

    # senior vs entry
    hi = df[df["exp_min"] >= 3]["skills"].tolist()
    lo = df[df["exp_min"] <= 1]["skills"].tolist()
    out["level_note"] = None
    if len(hi) >= MIN_GROUP and len(lo) >= MIN_GROUP:
        a, b = _share(hi), _share(lo)
        cnt = Counter(s for r in hi for s in set(r))
        lift = [{"skill": k, "senior": round(a[k] * 100, 1), "entry": round(b.get(k, 0) * 100, 1),
                 "lift": round((a[k] - b.get(k, 0)) * 100, 1), "have": k in have}
                for k in a if cnt[k] >= 4]
        out["level"] = sorted(lift, key=lambda m: -m["lift"])[:10]
        out["level_n"] = (len(hi), len(lo))
    else:
        out["level_note"] = f"Only {len(hi)} postings ask for 3+ years and {len(lo)} for 0-1; need {MIN_GROUP} of each."

    # salary
    sal = [(r, _annual_inr(r)) for r in rows]
    sal = [(r, v) for r, v in sal if v]
    out["n_salary"] = len(sal)
    if len(sal) >= MIN_SALARIES:
        base = median(v for _, v in sal)
        by = {}
        for r, v in sal:
            for s in set(r["skills"]):
                by.setdefault(s, []).append(v)
        out["salary_median"] = base
        out["pay"] = sorted([{"skill": k, "median": median(v), "jobs": len(v), "vs": round((median(v) / base - 1) * 100),
                              "have": k in have} for k, v in by.items() if len(v) >= 4], key=lambda m: -m["vs"])[:8]

    # your fit
    if mine:
        scored = []
        for r in rows:
            ok = years is None or r["exp_min"] is None or pd.isna(r["exp_min"]) or r["exp_min"] <= years + 1
            scored.append((r, ok, _match(r["skills"], have)))
        eligible = [(r, m) for r, ok, m in scored if ok]
        strong = [(r, m) for r, m in eligible if m >= STRONG]
        out["fit"] = {"eligible": len(eligible), "strong": len(strong), "too_senior": len(scored) - len(eligible),
                      "cities": Counter(r["search_city"] for r, _ in strong).most_common(3)}

        # which missing skill unlocks the most new strong matches
        near = [(r, m) for r, m in eligible if m < STRONG]
        learn = []
        for k, v in share.items():
            if k in have or v < 0.03:
                continue
            unlocked = sum(1 for r, m in near if k in r["skills"] and _match(r["skills"], have, 1) >= STRONG)
            learn.append({"skill": k, "share": round(v * 100, 1), "unlock": unlocked})
        out["learn"] = sorted(learn, key=lambda m: (-m["unlock"], -m["share"]))[:8]

        # scan tuning: which search terms actually surface good jobs
        yield_ = {}
        for r, m in eligible:
            y = yield_.setdefault(r["search_term"] or "?", [0, 0])
            y[0] += 1
            y[1] += m >= STRONG
        out["queries"] = sorted([{"term": t, "found": a, "strong": b, "rate": round(100 * b / a)}
                                 for t, (a, b) in yield_.items()], key=lambda q: -q["strong"])

        # plain-language takeaways
        tips = []
        if out["learn"] and out["learn"][0]["unlock"]:
            t = out["learn"][0]
            tips.append(f"Learn {t['skill']} first: it appears in {t['share']}% of postings and would lift {t['unlock']} "
                        f"more jobs to a {STRONG}%+ match.")
        if out["fit"]["too_senior"] > 0.3 * len(scored):
            tips.append(f"{out['fit']['too_senior']} of {len(scored)} postings ask for more experience than you have. "
                        "Prefer 'fresher', 'graduate' and 'SDE 1' searches over generic ones.")
        weak = [q for q in out["queries"] if q["found"] >= 10 and q["rate"] < 0.5 * (100 * out["fit"]["strong"] / max(out["fit"]["eligible"], 1))]
        if weak:
            tips.append("Low-yield searches you could drop: " + ", ".join(q["term"] for q in weak[:3]) + ".")
        if out["fit"]["cities"]:
            tips.append("Most strong matches are in " + ", ".join(c for c, _ in out["fit"]["cities"]) + ".")
        out["tips"] = tips
    return out
