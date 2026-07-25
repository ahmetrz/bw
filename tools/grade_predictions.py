#!/usr/bin/env python3
"""Grade recorded predictions against real results and report the running hit rate.

    python tools/grade_predictions.py

Reads data/predictions.jsonl (written by the daily run), finds the ones whose match has
since finished, settles each with engine/grade.py, and writes the outcome back. Prints
the per-day and cumulative hit rate, which is the number every future change to this
project should be judged against.

Result sources, per sport:
  football (1)      football-data.co.uk season CSVs — the same source the model is fitted
                    on, so team names already agree and no second name-matching layer is
                    needed. Updated a few times a week, so grading lags by days, not hours.
  table tennis (10) data/tt_results.jsonl, accumulated by tools/collect_tt.py.

Anything else stays PENDING rather than being guessed at. A prediction that cannot be
settled honestly must not be counted in either column: scoring it wrongly would corrupt
the very measurement the improvements are steered by.
"""
import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import grade  # noqa: E402
from engine.model_elo import _norm  # noqa: E402  (same normalizer the model matches with)

FDCOUK = "https://www.football-data.co.uk/mmz4281"
UA = "bw-scanner/1.0 (result grading; contact via repo)"


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def football_results(divisions, season="2526"):
    """(normalized home, normalized away) -> (home goals, away goals)."""
    out = {}
    for d in divisions:
        try:
            req = urllib.request.Request(f"{FDCOUK}/{season}/{d}.csv",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read().decode("utf-8-sig", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        for rec in csv.DictReader(io.StringIO(raw)):
            try:
                hg, ag = int(rec["FTHG"]), int(rec["FTAG"])
            except (KeyError, TypeError, ValueError):
                continue
            h, a = _norm(rec.get("HomeTeam")), _norm(rec.get("AwayTeam"))
            if h and a:
                out[(h, a)] = (hg, ag)
    return out


def tt_results(path="data/tt_results.jsonl"):
    """(normalized p1, normalized p2) -> (sets won by p1, sets won by p2)."""
    out = {}
    for m in load_jsonl(path):
        p1, p2 = _norm(m.get("p1_name")), _norm(m.get("p2_name"))
        sets = m.get("sets") or []
        if p1 and p2 and len(sets) == 2:
            out[(p1, p2)] = (sets[0], sets[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", default="data/predictions.jsonl")
    ap.add_argument("--out", default="data/scoreboard.json")
    ap.add_argument("--season", default="2526")
    args = ap.parse_args()

    preds = load_jsonl(args.predictions)
    if not preds:
        print("no predictions recorded yet — nothing to grade")
        return 0

    pending = [p for p in preds if not p.get("result")]
    print(f"predictions: {len(preds)} total, {len(pending)} ungraded")

    divisions = sorted({p["division"] for p in pending
                        if p.get("sport_id") == 1 and p.get("division")})
    results_fb = football_results(divisions, args.season) if divisions else {}
    results_tt = tt_results()
    print(f"result rows available: football {len(results_fb)}, table tennis {len(results_tt)}")

    newly = 0
    for p in pending:
        key = (_norm(p.get("p1")), _norm(p.get("p2")))
        score = results_fb.get(key) if p.get("sport_id") == 1 else results_tt.get(key)
        if not score:
            continue
        row = {"market_key": (0, p["market_line"]), "outcome_id": p.get("outcome_id")}
        outcome = grade.settle(row, score[0], score[1])
        if outcome is None:
            # An unsupported market must stay pending rather than be scored on a guess.
            continue
        p["result"] = outcome
        p["final_score"] = list(score)
        p["graded_at"] = datetime.now(timezone.utc).isoformat()
        newly += 1

    if newly:
        write_jsonl(args.predictions, preds)
    print(f"newly graded: {newly}")

    graded = [p for p in preds if p.get("result")]
    overall = grade.summarize(graded)
    by_day = {}
    per_day = defaultdict(list)
    for p in graded:
        per_day[(p.get("date") or "?")].append(p)
    for day, rows in sorted(per_day.items()):
        by_day[day] = grade.summarize(rows)

    board = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "by_day": by_day,
        "pending": len([p for p in preds if not p.get("result")]),
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(board, f, indent=2, ensure_ascii=False)

    print()
    if overall:
        print(f"OVERALL  graded {overall['graded']} | "
              f"W {overall['win']} · half {overall['half']} · push {overall['push']} · L {overall['loss']} | "
              f"hit {overall['hit_rate']:.1%} | return {overall['returned']:.2f} on "
              f"{overall['staked']} staked ({overall['roi_pct']:+.1f}%)")
        for day, s in sorted(by_day.items()):
            print(f"  {day}: {s['graded']:>3} graded, hit {s['hit_rate']:.1%}, "
                  f"ROI {s['roi_pct']:+.1f}%")
    else:
        print("nothing graded yet")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
