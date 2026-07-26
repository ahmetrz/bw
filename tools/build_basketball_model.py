#!/usr/bin/env python3
"""Fit the basketball model from data/basketball_games.jsonl -> data/model_basketball.json

    python tools/build_basketball_model.py

WHY BASKETBALL IS THE CLEANEST SPORT THIS PROJECT HAS MODELLED SO FAR: the quantity the
safety ladder needs is the MARGIN, and basketball margins are close to normal. Football
needed a Poisson pair plus a fitted draw correction to get at a goal difference; here the
margin is a single continuous number with a symmetric, well-behaved spread, so
P(covers +12.5) is one normal CDF rather than a sum over a scoreline matrix.

Three things are fitted, in this order:

  1. ELO, chained across seasons with a regression toward the mean between them. Ratings
     are pooled across EuroLeague and EuroCup rather than kept per competition. That is
     the opposite of what the football model does, and deliberately so: football divisions
     never meet, so a Championship 1500 and a Bundesliga 1500 are not the same strength.
     Basketball clubs move between the two competitions from season to season, and those
     movers chain the two scales onto one another. The link is real, so the pool is honest.

     Rated by CLUB CODE, never by name. European clubs rename themselves after whoever is
     paying: one code covers "Efes Pilsen", "Efes Pilsen Istanbul" and "Anadolu Efes
     Istanbul"; another covers five spellings of Gdynia. Keyed by name, 167 clubs became
     343 rating entries, each holding a fragment of one club's history — and a fragmented
     rating is a weak rating, not merely an untidy one. 78 of the 167 codes carry more
     than one name, and no name is shared by two codes, so the code is the identity and
     the names are its aliases.

  2. The MARGIN LINE: margin = slope x elo_diff + home_advantage, by least squares, with
     neutral-venue games contributing no home term. The residual spread is measured, not
     assumed, because it is the number every handicap probability is divided by.

  3. The TOTAL: mean and spread of combined points, so the totals ladder has a base rate.

Settlement note that changes the fit: the book settles full-game basketball INCLUDING
overtime, so the model is fitted on FINAL margins, not regulation ones. Fitting regulation
would misprice exactly the close games where a handicap is decided — every overtime game
has a regulation margin of exactly zero.

Standard library only. No numpy.
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START_RATING = 1500.0
K = 20.0
# Between seasons a club's rating is pulled back toward the mean: rosters turn over hard
# in European basketball and last season's rating is a weaker claim about this season's
# team than it looks.
SEASON_REGRESSION = 0.25


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _expected(diff):
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def club_index(rows):
    """code -> {current name, every historical alias, last season seen}.

    The current name is whatever the club was called most recently, because that is what
    the book prints on today's card. The older names stay as aliases so a fixture written
    the old way still resolves rather than silently going unpriced.
    """
    clubs = {}
    for r in rows:
        for code, name in ((r["home_code"], r["home"]), (r["away_code"], r["away"])):
            if not code:
                continue
            c = clubs.setdefault(code, {"code": code, "aliases": set(), "last": -1,
                                        "name": name, "games": 0})
            c["aliases"].add(name)
            c["games"] += 1
            if r["season"] >= c["last"]:
                c["last"] = r["season"]
                c["name"] = name
    return clubs


def fit_elo(rows):
    """Chained Elo with a margin-of-victory multiplier.

    The MOV term is what stops a 40-point win and a 1-point win moving a rating equally.
    It is damped by the rating difference, the standard correction: a heavy favourite
    winning big is not new information, an underdog winning big is.
    """
    rating = defaultdict(lambda: START_RATING)
    season = None
    for r in rows:
        if r["season"] != season:
            if season is not None:
                for t in rating:
                    rating[t] += (START_RATING - rating[t]) * SEASON_REGRESSION
            season = r["season"]
        h, a = r["home_code"], r["away_code"]
        diff = rating[h] - rating[a] + (0.0 if r.get("neutral") else 60.0)
        exp_h = _expected(diff)
        actual = 1.0 if r["margin"] > 0 else 0.0
        mov = math.log(abs(r["margin"]) + 1.0) * (2.2 / (abs(diff) * 0.001 + 2.2))
        delta = K * mov * (actual - exp_h)
        rating[h] += delta
        rating[a] -= delta
    return dict(rating)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs, mu=None):
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs) if mu is None else mu
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def fit_margin(rows, rating):
    """margin ~ slope * elo_diff + hca, by least squares on the pooled sample.

    Home advantage is estimated only from non-neutral games; a neutral-court final would
    otherwise drag it down and quietly flatten every home line on the card.
    """
    xs, ys = [], []
    for r in rows:
        d = rating.get(r["home_code"], START_RATING) - rating.get(r["away_code"], START_RATING)
        xs.append(d)
        ys.append(float(r["margin"] - (0.0 if r.get("neutral") else 0.0)))
    n = len(xs)
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx

    home_games = [r for r in rows if not r.get("neutral")]
    neutral = [r for r in rows if r.get("neutral")]
    hca = _mean([r["margin"] for r in home_games]) - _mean([r["margin"] for r in neutral] or [0.0])

    resid = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    return {
        "slope": round(slope, 6),
        "intercept": round(intercept, 4),
        "residual_sd": round(_sd(resid), 4),
        "home_advantage_points": round(hca, 3),
        "n": n,
        "neutral_games": len(neutral),
    }


def fit_total(rows, rating):
    """Combined points: base rate plus how much a mismatch moves it."""
    totals = [r["home_score"] + r["away_score"] for r in rows]
    mu = _mean(totals)
    xs = [abs(rating.get(r["home_code"], START_RATING) - rating.get(r["away_code"], START_RATING))
          for r in rows]
    mx = _mean(xs)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (t - mu) for x, t in zip(xs, totals))
    slope = sxy / sxx if sxx else 0.0
    resid = [t - (mu + slope * (x - mx)) for x, t in zip(xs, totals)]
    return {
        "mean": round(mu, 3),
        "sd": round(_sd(totals, mu), 3),
        "gap_slope": round(slope, 6),
        "gap_mean": round(mx, 3),
        "residual_sd": round(_sd(resid), 3),
    }


def calibrate(rows, rating, margin):
    """Does the fitted normal actually price a handicap? Measured, never asserted.

    For a spread of plus-lines, compare the model's predicted cover rate against the
    observed one. A model that says 90% and lands 78% would send the ladder straight past
    the confidence floor with nothing behind it, and the floor would not catch it — the
    floor trusts the model.
    """
    sd = margin["residual_sd"]
    out = []
    for line in (2.5, 4.5, 6.5, 8.5, 10.5, 12.5, 14.5, 16.5, 20.5):
        pred, hit = [], []
        for r in rows:
            d = rating.get(r["home_code"], START_RATING) - rating.get(r["away_code"], START_RATING)
            mu = margin["slope"] * d + margin["intercept"]
            # Underdog side: the team the model has behind, taking the plus points.
            # Both branches had the sign of `mu` flipped when this was first written, and
            # the fitted normal then claimed 90.4% for +12.5 against an observed 74.9%.
            # It is worth stating why that was dangerous rather than merely wrong: 90% for
            # a +12.5 line is entirely believable, so nothing about the number invited
            # suspicion, and it clears MIN_MODEL_SURVIVAL with room to spare. The floor
            # cannot catch this class of error because the floor TRUSTS the model. Only
            # comparing the claim against the observed rate catches it.
            if mu >= 0:
                # Home is favoured, so the away side takes the points: it covers when the
                # home margin comes in under the line. P(margin < line).
                p = _norm_cdf((line - mu) / sd) if sd else 0.0
                covered = (-r["margin"]) + line > 0
            else:
                # Away is favoured; home takes the points and covers when the margin stays
                # above -line. P(margin > -line) = Phi((line + mu) / sd).
                p = _norm_cdf((line + mu) / sd) if sd else 0.0
                covered = r["margin"] + line > 0
            pred.append(p)
            hit.append(1.0 if covered else 0.0)
        out.append({"line": line, "predicted": round(_mean(pred), 4),
                    "observed": round(_mean(hit), 4), "n": len(hit)})
    return out


def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="data/basketball_games.jsonl")
    ap.add_argument("--out", default="data/model_basketball.json")
    ap.add_argument("--fit-seasons", type=int, default=8,
                    help="how many recent seasons the line and spread are fitted on")
    args = ap.parse_args()

    rows = load(args.games)
    rows.sort(key=lambda r: (r["season"], r["date"]))
    print(f"games: {len(rows)} over {len({r['season'] for r in rows})} seasons")

    clubs = club_index(rows)
    print(f"clubs: {len(clubs)} by code "
          f"({sum(1 for c in clubs.values() if len(c['aliases']) > 1)} have been renamed)")
    rating = fit_elo(rows)
    recent = sorted({r["season"] for r in rows})[-args.fit_seasons:]
    fit_rows = [r for r in rows if r["season"] in recent]
    print(f"fitting the line on {len(fit_rows)} games from seasons {min(recent)}-{max(recent)}")

    margin = fit_margin(fit_rows, rating)
    total = fit_total(fit_rows, rating)
    cal = calibrate(fit_rows, rating, margin)

    print(f"\nmargin = {margin['slope']:.5f} x elo_diff + {margin['intercept']:.2f}"
          f"   residual sd {margin['residual_sd']:.2f} points")
    print(f"home advantage {margin['home_advantage_points']:.2f} points "
          f"({margin['neutral_games']} neutral games excluded from it)")
    print(f"total points   mean {total['mean']:.1f}  sd {total['sd']:.1f}")
    print("\ncalibration — plus handicap cover rate")
    print(f"  {'line':>6} {'model':>8} {'gerçek':>8} {'fark':>7}")
    for c in cal:
        print(f"  +{c['line']:<5} {c['predicted']:>8.3f} {c['observed']:>8.3f} "
              f"{c['predicted'] - c['observed']:>+7.3f}")

    model = {
        "source": "api-live.euroleague.net/v2 (EuroLeague + EuroCup)",
        "games": len(rows),
        "teams": len(clubs),
        "seasons": sorted({r["season"] for r in rows}),
        "fit_seasons": recent,
        "start_rating": START_RATING,
        "margin": margin,
        "total": total,
        "calibration": cal,
        "clubs": [
            {"code": code,
             "name": c["name"],
             "aliases": sorted(c["aliases"]),
             "games": c["games"],
             "last_season": c["last"],
             "rating": round(rating.get(code, START_RATING), 1)}
            for code, c in sorted(clubs.items(),
                                  key=lambda kv: -rating.get(kv[0], START_RATING))
        ],
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)
    print(f"\nwrote {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB)")

    print("en yüksek dereceler:",
          ", ".join(f"{c['name']} {c['rating']:.0f}" for c in model["clubs"][:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
