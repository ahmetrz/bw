#!/usr/bin/env python3
"""Calibrate a table-tennis model from harvested head-to-head history.

    python tools/build_tt_model.py --out data/model_tt.json

Table tennis is 372 of a 1,607-match card — the largest block after football — and it
produced no selections at all because the rating scale had never been turned into a
probability. Setka publishes a rating; what it MEANS in win-probability terms is not
published, and assuming a mapping would have been exactly the kind of guess this project
refuses.

So it is fitted, on real outcomes:
  1. P(stronger player wins) as a logistic in the rating difference, by maximum
     likelihood (Newton's method, no third-party packages).
  2. The SET-SCORE distribution conditional on the rating gap, binned empirically —
     3-0 / 3-1 / 3-2 is what decides whether "+1.5 sets" or "+2.5 sets" is the safe rung,
     and that distribution is the set-handicap market itself. It is measured rather than
     derived, because a per-point model would need serve data nobody publishes.

RECENCY. The archive reaches back to 2018 but the ratings are CURRENT, so an old match
pairs today's rating with a player who was not that strong at the time. The fit is
therefore run on a recent window by default, and the script reports both so the size of
that effect is visible instead of assumed.
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import setka  # noqa: E402


def load_history(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def fit_logistic(samples, iters=60):
    """P(win) = 1 / (1 + exp(-(a + b*x))) by Newton-Raphson on the log-likelihood.

    `samples` is [(rating_difference, won)]. Two parameters, so the Hessian is 2x2 and
    can be inverted in closed form — no linear algebra dependency needed.
    """
    a, b = 0.0, 0.02
    for _ in range(iters):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for x, y in samples:
            z = a + b * x
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            r = y - p
            w = p * (1.0 - p)
            g_a += r
            g_b += r * x
            h_aa += w
            h_ab += w * x
            h_bb += w * x * x
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (h_aa * g_b - h_ab * g_a) / det
        a += da
        b += db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, b


def log_loss(samples, a, b):
    tot = 0.0
    for x, y in samples:
        z = max(-30.0, min(30.0, a + b * x))
        p = 1.0 / (1.0 + math.exp(-z))
        p = min(max(p, 1e-9), 1 - 1e-9)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / len(samples) if samples else float("nan")


def calibration_table(samples, a, b, bins=8):
    """Predicted vs observed, which is the only honest check that the fit is usable."""
    rows = []
    for x, y in samples:
        z = max(-30.0, min(30.0, a + b * x))
        rows.append((1.0 / (1.0 + math.exp(-z)), y))
    rows.sort()
    out, size = [], max(1, len(rows) // bins)
    for i in range(0, len(rows), size):
        chunk = rows[i:i + size]
        if len(chunk) < 20:
            continue
        out.append({
            "n": len(chunk),
            "predicted": round(sum(p for p, _ in chunk) / len(chunk), 4),
            "observed": round(sum(y for _, y in chunk) / len(chunk), 4),
        })
    return out


def set_distribution(rows, ratings, edges=(0, 3, 6, 10, 100)):
    """Observed set scorelines, binned by the rating gap, always from the FAVOURITE's view.

    Orienting on the favourite rather than on player 1 is what makes the bins meaningful:
    it turns two mirror-image scorelines into one statement about how decisively the
    stronger player tends to win.
    """
    buckets = defaultdict(Counter)
    for r in rows:
        r1, r2 = ratings.get(r["p1_id"]), ratings.get(r["p2_id"])
        if r1 is None or r2 is None:
            continue
        gap = abs(r1 - r2)
        fav_is_p1 = r1 >= r2
        s1, s2 = r["sets"]
        fav, dog = (s1, s2) if fav_is_p1 else (s2, s1)
        for lo, hi in zip(edges, edges[1:]):
            if lo <= gap < hi:
                buckets[f"{lo}-{hi}"][f"{fav}-{dog}"] += 1
                break
    out = {}
    for key, counter in buckets.items():
        total = sum(counter.values())
        out[key] = {"n": total,
                    "dist": {k: round(v / total, 4) for k, v in sorted(counter.items())}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="data/tt_history.jsonl")
    ap.add_argument("--out", default="data/model_tt.json")
    ap.add_argument("--since", default="2024-01-01",
                    help="fit window; ratings are current, so old matches pair today's "
                         "rating with a different player")
    args = ap.parse_args()

    rows = load_history(args.history)
    print(f"history: {len(rows)} matches")

    print("fetching current ratings ...")
    players = setka.ratings()
    ratings = {pid: p.get("ratingSc") for pid, p in players.items()
               if p.get("ratingSc") is not None}
    print(f"rated players: {len(ratings)}")

    def samples_from(subset):
        out = []
        for r in subset:
            r1, r2 = ratings.get(r["p1_id"]), ratings.get(r["p2_id"])
            if r1 is None or r2 is None:
                continue
            out.append((r1 - r2, 1 if r["p1_won"] else 0))
        return out

    all_s = samples_from(rows)
    recent_rows = [r for r in rows if (r.get("start") or "") >= args.since]
    rec_s = samples_from(recent_rows)
    print(f"usable samples: {len(all_s)} all-time, {len(rec_s)} since {args.since}")
    if len(rec_s) < 300:
        print("not enough recent samples to fit — refusing", file=sys.stderr)
        return 1

    a_all, b_all = fit_logistic(all_s)
    a, b = fit_logistic(rec_s)
    print(f"\n  all-time : P(win) = logistic({a_all:.4f} + {b_all:.5f} * ratingdiff)  "
          f"logloss {log_loss(all_s, a_all, b_all):.4f}")
    print(f"  recent   : P(win) = logistic({a:.4f} + {b:.5f} * ratingdiff)  "
          f"logloss {log_loss(rec_s, a, b):.4f}")
    # A coin flip is 0.693; anything close to it means the rating carries no signal.
    print(f"  baseline (always 0.5): {math.log(2):.4f}")

    print("\ncalibration (predicted vs observed), recent fit:")
    table = calibration_table(rec_s, a, b)
    for row in table:
        print(f"   n={row['n']:>5}  predicted {row['predicted']:.3f}  "
              f"observed {row['observed']:.3f}  diff {row['observed'] - row['predicted']:+.3f}")

    sets = set_distribution(recent_rows, ratings)
    print("\nset scorelines by rating gap (favourite's view):")
    for key in sorted(sets, key=lambda k: float(k.split("-")[0])):
        d = sets[key]
        top = " ".join(f"{k}:{v:.2f}" for k, v in sorted(d["dist"].items(), reverse=True)[:6])
        print(f"   gap {key:<7} n={d['n']:>5}  {top}")

    model = {
        "source": "setka compare archive",
        "fitted_on": args.since,
        "samples": len(rec_s),
        "logistic": {"a": round(a, 6), "b": round(b, 8)},
        "logloss": round(log_loss(rec_s, a, b), 5),
        "baseline_logloss": round(math.log(2), 5),
        "calibration": table,
        "set_distribution": sets,
        "rating_span": [min(ratings.values()), max(ratings.values())],
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(model, f, indent=1)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
