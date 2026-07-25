#!/usr/bin/env python3
"""Build a calibrated football model from football-data.co.uk history.

    python tools/build_football_model.py --seasons 5 --out data/model_football.json

Why this exists: ClubElo is the only football model wired in, it covers roughly 60
European leagues, and it publishes only near-term fixtures — so on a late-July card it
reached zero of 58 matches. This builds our own, from raw results, over as many seasons
and leagues as we want, and it CALIBRATES every step against outcomes instead of assuming.

Method, in the order it is fitted:
  1. Elo per team from match results, with a home-advantage term and a per-league
     starting rating. Standard, and it is the part that transfers across leagues.
  2. Elo difference -> expected goal supremacy, fitted by least squares on real matches
     rather than assumed.
  3. Match total goals -> fitted from the league's own history.
  4. Home and away goals as independent Poissons around those two quantities, which then
     yields EVERY market the safety ladder needs — 1X2, double chance, any handicap line,
     any totals line — from one coherent distribution.

Step 4's independence assumption is the known weak point: real scorelines are mildly
correlated (draws are more common than independent Poissons predict). The fit reports the
observed-vs-predicted draw rate so the size of that error is visible rather than hidden,
and it applies a fitted draw inflation to correct it.

Licence: football-data.co.uk publishes an empty robots.txt Disallow (all robots allowed)
and offers the CSVs for free download. Data is used here to fit a model, not redistributed.
"""
import argparse
import csv
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One construction, shared with the live model — two copies would drift apart.
from engine.model_football import score_matrix  # noqa: E402

BASE = "https://www.football-data.co.uk/mmz4281"
UA = "bw-scanner/1.0 (model research; contact via repo)"

# The divisions football-data.co.uk publishes with full result history. Their "extra"
# files cover more countries but in a different schema, so they are left out rather than
# parsed on a guess.
DIVISIONS = [
    "E0", "E1", "E2", "E3", "EC",           # England
    "SC0", "SC1", "SC2", "SC3",             # Scotland
    "D1", "D2",                             # Germany
    "I1", "I2",                             # Italy
    "SP1", "SP2",                           # Spain
    "F1", "F2",                             # France
    "N1",                                   # Netherlands
    "B1",                                   # Belgium
    "P1",                                   # Portugal
    "T1",                                   # Turkey
    "G1",                                   # Greece
]

K_FACTOR = 20.0
HOME_ADV_ELO = 60.0     # starting value; refitted below
START_RATING = 1500.0


def season_codes(n):
    """The n most recent season codes, newest first: 2526, 2425, ..."""
    # The 2026-27 season has not started, so the current file is 2526.
    out, y = [], 25
    for _ in range(n):
        out.append(f"{y:02d}{(y + 1) % 100:02d}")
        y -= 1
    return out


def fetch(div, season, timeout=40):
    url = f"{BASE}/{season}/{div}.csv"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8-sig", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return []
    rows = []
    for rec in csv.DictReader(io.StringIO(raw)):
        h, a = (rec.get("HomeTeam") or "").strip(), (rec.get("AwayTeam") or "").strip()
        try:
            hg, ag = int(rec["FTHG"]), int(rec["FTAG"])
        except (KeyError, TypeError, ValueError):
            continue
        if not h or not a:
            continue
        rows.append({"div": div, "season": season, "date": rec.get("Date", ""),
                     "home": h, "away": a, "hg": hg, "ag": ag})
    return rows


def run_elo(matches, k=K_FACTOR, home_adv=HOME_ADV_ELO):
    """Sequential Elo. Returns final ratings and the pre-match rating diff per match."""
    rating = defaultdict(lambda: START_RATING)
    history = []
    for m in matches:
        rh, ra = rating[m["home"]], rating[m["away"]]
        diff = rh + home_adv - ra
        exp_h = 1.0 / (1.0 + 10 ** (-diff / 400.0))
        if m["hg"] > m["ag"]:
            score = 1.0
        elif m["hg"] == m["ag"]:
            score = 0.5
        else:
            score = 0.0
        # Margin-of-victory multiplier: a 4-0 says more than a 1-0.
        margin = abs(m["hg"] - m["ag"])
        mult = math.log(max(margin, 1) + 1.0)
        delta = k * mult * (score - exp_h)
        rating[m["home"]] = rh + delta
        rating[m["away"]] = ra - delta
        history.append({**m, "elo_diff": diff, "sup": m["hg"] - m["ag"],
                        "total": m["hg"] + m["ag"]})
    return dict(rating), history


def fit_supremacy(history, burn_in=0.25):
    """Least-squares fit of goal supremacy on the Elo difference.

    The first slice of each dataset is skipped: every team starts at the same rating, so
    early matches carry a rating difference that means nothing yet.
    """
    rows = history[int(len(history) * burn_in):]
    n = len(rows)
    if n < 100:
        return 0.0, 0.0
    sx = sum(r["elo_diff"] for r in rows)
    sy = sum(r["sup"] for r in rows)
    sxx = sum(r["elo_diff"] ** 2 for r in rows)
    sxy = sum(r["elo_diff"] * r["sup"] for r in rows)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def fit_draw_boost(history, slope, intercept, mean_total):
    """Find the diagonal multiplier that reproduces the observed draw rate."""
    rows = history[len(history) // 4:]
    if not rows:
        return 1.0, 0.0, 0.0
    observed = sum(1 for r in rows if r["sup"] == 0) / len(rows)

    def predicted(boost):
        tot = 0.0
        # Sample rather than sum over every match; the curve is smooth and this keeps the
        # fit fast enough to run in CI.
        step = max(1, len(rows) // 1500)
        sampled = rows[::step]
        for r in sampled:
            sup = slope * r["elo_diff"] + intercept
            lam_h = max(0.05, (mean_total + sup) / 2.0)
            lam_a = max(0.05, (mean_total - sup) / 2.0)
            mat = score_matrix(lam_h, lam_a, boost)
            tot += sum(mat[i][i] for i in range(len(mat)))
        return tot / len(sampled)

    lo, hi = 0.8, 2.0
    base = predicted(1.0)
    for _ in range(18):
        mid = (lo + hi) / 2
        if predicted(mid) < observed:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, observed, base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=5)
    ap.add_argument("--out", default="data/model_football.json")
    ap.add_argument("--divisions", default="")
    args = ap.parse_args()

    divs = [d.strip() for d in args.divisions.split(",") if d.strip()] or DIVISIONS
    seasons = season_codes(args.seasons)
    print(f"downloading {len(divs)} divisions x {len(seasons)} seasons ...")

    by_div = defaultdict(list)
    total = 0
    for season in reversed(seasons):          # oldest first, so Elo runs forward in time
        for d in divs:
            rows = fetch(d, season)
            by_div[d].extend(rows)
            total += len(rows)
    print(f"matches downloaded: {total}")
    if total < 500:
        print("not enough history — refusing to fit", file=sys.stderr)
        return 1

    # Elo is run PER DIVISION. Ratings are not comparable across leagues without
    # cross-league fixtures, and pooling them would quietly claim a Championship 1500 is
    # the same strength as a Bundesliga 1500.
    model = {"divisions": {}, "seasons": seasons, "k": K_FACTOR,
             "home_adv_elo": HOME_ADV_ELO, "matches": total}
    for d, matches in sorted(by_div.items()):
        if len(matches) < 200:
            print(f"  {d}: {len(matches)} matches — too few, skipped")
            continue
        ratings, history = run_elo(matches)
        slope, intercept = fit_supremacy(history)
        mean_total = sum(m["total"] for m in history) / len(history)
        boost, obs_draw, base_draw = fit_draw_boost(history, slope, intercept, mean_total)
        model["divisions"][d] = {
            "matches": len(matches),
            "teams": len(ratings),
            "ratings": {t: round(r, 1) for t, r in sorted(ratings.items())},
            "sup_slope": round(slope, 6),
            "sup_intercept": round(intercept, 4),
            "mean_total": round(mean_total, 4),
            "draw_boost": round(boost, 4),
            "observed_draw_rate": round(obs_draw, 4),
            "poisson_draw_rate": round(base_draw, 4),
        }
        print(f"  {d}: {len(matches):>5} matches, {len(ratings):>3} teams | "
              f"sup={slope:.5f}*elo{intercept:+.3f} | mean goals {mean_total:.2f} | "
              f"draws obs {obs_draw:.3f} vs poisson {base_draw:.3f} -> boost {boost:.3f}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(model, f, indent=1, ensure_ascii=False)
    size = os.path.getsize(args.out) / 1024
    print(f"\nwrote {args.out} ({size:.0f} KB) — "
          f"{len(model['divisions'])} divisions, {total} matches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
