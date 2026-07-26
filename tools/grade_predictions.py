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


EXTRA = "https://www.football-data.co.uk/new"


def football_results(divisions, season="2526"):
    """(normalized home, normalized away) -> (home goals, away goals).

    Divisions come in TWO shapes, because the model is fitted from two collections.
    A main division is a bare code ("E0"); a summer league is "COUNTRY:League"
    ("ARG:Liga Profesional") and lives in a per-country file with a different schema.
    Fetching the second as if it were the first produced a URL containing a space, which
    is an InvalidURL rather than a 404 — it crashed the grader instead of skipping.
    """
    out = {}
    countries = {d.split(":", 1)[0] for d in divisions if ":" in d}
    mains = [d for d in divisions if ":" not in d]

    def absorb(raw, home_key, away_key, hg_key, ag_key):
        for rec in csv.DictReader(io.StringIO(raw)):
            try:
                hg, ag = int(rec[hg_key]), int(rec[ag_key])
            except (KeyError, TypeError, ValueError):
                continue
            h, a = _norm(rec.get(home_key)), _norm(rec.get(away_key))
            if not (h and a):
                continue
            # Keyed by DATE as well as the two teams. Without it the same pairing from
            # earlier in the season answers for tonight's fixture — which is exactly what
            # happened: 31 predictions all starting in the future came back "graded",
            # 87.1% of them winners, entirely from previous meetings. A hit rate built
            # that way is not merely wrong, it would have steered every later change.
            out.setdefault((h, a), []).append((_date(rec.get("Date")), hg, ag))

    def fetch(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8-sig", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError, ValueError):
            return None

    for d in mains:
        raw = fetch(f"{FDCOUK}/{season}/{d}.csv")
        if raw:
            absorb(raw, "HomeTeam", "AwayTeam", "FTHG", "FTAG")
    for c in sorted(countries):
        raw = fetch(f"{EXTRA}/{c}.csv")
        if raw:
            absorb(raw, "Home", "Away", "HG", "AG")
    return out


def _date(raw):
    """football-data.co.uk writes dd/mm/yy or dd/mm/yyyy. Returns YYYY-MM-DD or ''."""
    parts = (raw or "").strip().split("/")
    if len(parts) != 3:
        return ""
    d, m, y = parts
    if len(y) == 2:
        y = f"20{y}"
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def lookup_result(table, home, away, start, tolerance_days=1):
    """The result for THIS fixture, matched on date as well as on the two teams.

    A one-day tolerance absorbs the timezone gap between the book's kick-off stamp and the
    results file's local date. Anything looser would start matching neighbouring fixtures.
    """
    from datetime import date, timedelta

    entries = table.get((_norm(home), _norm(away)))
    if not entries:
        return None
    want = (start or "")[:10]
    if not want:
        return None
    try:
        target = date.fromisoformat(want)
    except ValueError:
        return None
    for when, hg, ag in entries:
        try:
            got = date.fromisoformat(when)
        except ValueError:
            continue
        if abs((got - target).days) <= tolerance_days:
            return (hg, ag)
    return None


def tt_results(path="data/tt_results.jsonl"):
    """(normalized p1, normalized p2) -> (sets won by p1, sets won by p2)."""
    out = {}
    for m in load_jsonl(path):
        p1, p2 = _norm(m.get("p1_name")), _norm(m.get("p2_name"))
        sets = m.get("sets") or []
        if p1 and p2 and len(sets) == 2:
            out.setdefault((p1, p2), []).append(((m.get("start") or "")[:10],
                                                 sets[0], sets[1]))
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

    now = datetime.now(timezone.utc).isoformat()
    newly = skipped_future = 0
    for p in pending:
        # A fixture that has not started cannot have a result. Guarding on this as well as
        # on the date match, because a grader that can score an unplayed match is a grader
        # that will eventually score one wrongly.
        if (p.get("start") or "") > now:
            skipped_future += 1
            continue
        table = results_fb if p.get("sport_id") == 1 else results_tt
        score = lookup_result(table, p.get("p1"), p.get("p2"), p.get("start"))
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
    print(f"newly graded: {newly} | not started yet: {skipped_future}")

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
