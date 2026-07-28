#!/usr/bin/env python3
"""Grade recorded predictions against real results and report the running hit rate.

    python tools/grade_predictions.py

Reads data/predictions.jsonl (written by the daily run), finds the ones whose match has
since finished, settles each with engine/grade.py, and writes the outcome back. Prints
the per-day and cumulative hit rate, which is the number every future change to this
project should be judged against.

Result sources, in the order they are tried:

  1. data/results/<sport>.jsonl — THE RESULTS STORE, and now the main source for every
     sport. What the live watcher records comes off the same feed the card is built from,
     so a watched result carries the BOOK'S OWN participant ids and the prediction carries
     the same two ids. That match is exact. No normalizer, no fuzzy threshold, no chance
     of resolving to a different team with a similar name — and it covers snooker, darts,
     volleyball and everything else the moment the watcher sees them, not only the two
     sports somebody happened to write an archive adapter for.
  2. football-data.co.uk season CSVs, for football fixtures the watcher did not see. It
     is the source the football model is fitted on, so the names already agree, but it
     updates a few times a week — grading through it lags by days.
  3. data/tt_results.jsonl, the older table tennis collector.

WHY THIS ORDER CHANGED. Grading used to know about exactly those last two, so every
other sport stayed PENDING for ever: 99 predictions were logged and 99 were ungraded,
and the project's own live performance — the number every future change is supposed to be
judged against — was simply not being measured. The watcher had been recording the
results the whole time; nothing was reading them.

Anything still unmatched stays PENDING rather than being guessed at. A prediction that
cannot be settled honestly must not be counted in either column: scoring it wrongly would
corrupt the very measurement the improvements are steered by.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import grade, results_store  # noqa: E402
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


def lookup_result(table, home, away, start, tolerance_days=1, elapsed_hours=None):
    """The result for THIS fixture, matched on date as well as on the two teams.

    A one-day tolerance absorbs the timezone gap between the book's kick-off stamp and the
    results file's local date. Anything looser would start matching neighbouring fixtures.
    """
    return _nearest(table.get((_norm(home), _norm(away))), start, tolerance_days,
                    elapsed_hours)


def store_results(sport_id):
    """Two lookups over data/results/<sport>.jsonl: one keyed on the book's ids, one on
    normalized names. Both map to [(date, home score, away score)].

    The id table only holds rows the live watcher wrote, because only those ids came from
    Betwinner. A source's own id — EuroLeague's club code, Setka's player number, MLB's
    team id — identifies the team inside THAT source and means nothing on the book's card;
    keying on it would settle a fixture from whatever unrelated team shared a number.
    """
    by_id, by_name = {}, {}
    for r in results_store.load(sport_id):
        entry = (r["date"], r["home_score"], r["away_score"])
        # AND THE SAME FIXTURE THE OTHER WAY ROUND, with the scores swapped to match.
        # Which participant is "home" is a property of the SOURCE, not of the match: in
        # table tennis and tennis there is no home side at all, so the book's O1/O2 and
        # Setka's p1/p2 are ordered independently. Keying only one way silently lost
        # results that were sitting in the store — and losing them is the safe failure,
        # while forgetting to swap the scores would settle the bet against the wrong
        # player, which is the unsafe one.
        flipped = (r["date"], r["away_score"], r["home_score"])
        h, a = _norm(r.get("home")), _norm(r.get("away"))
        if h and a:
            by_name.setdefault((h, a), []).append(entry)
            by_name.setdefault((a, h), []).append(flipped)
        if r.get("source") == "betwinner-live" and r.get("home_id") and r.get("away_id"):
            hid, aid = str(r["home_id"]), str(r["away_id"])
            by_id.setdefault((hid, aid), []).append(entry)
            by_id.setdefault((aid, hid), []).append(flipped)
    return by_id, by_name


# A RESULTS SITE PRINTS "Fritz T." AND THE BOOK PRINTS "Taylor Harry Fritz".
#
# Both name the same player and neither normalizes to the other, so an exact-name index
# misses every row from a source that abbreviates — which is every live-score site there
# is. Tennis is where this bites: the book's card carries full names, tennisexplorer's
# results carry surname plus initial, and without a bridge the whole sport stays ungraded.
#
# The bridge is a containment test rather than a key, so it cannot be a dict lookup:
#   * every token of the page's SURNAME must appear as a contiguous run in the book's
#     name — "Martinez" inside "Pedro Martinez Portero", which is how a Spanish double
#     surname survives being printed with only its first half;
#   * and the book's first token must start with the page's INITIAL.
# Both sides must match for both players before a row settles anything.
_WORD = re.compile(r"[^a-z]+")


def _tokens_of(name):
    return [t for t in _WORD.split((name or "").lower()) if t]


def abbreviated(name):
    """(surname tokens, initial) for "Fritz T.", or None when the name is not abbreviated.

    The trailing single letter IS the test. A football club never ends in one, so an index
    built on this quietly stays empty for the sports where surname matching would be
    nonsense — no list of which sports are played by people is needed.
    """
    parts = _tokens_of(name)
    if len(parts) >= 2 and len(parts[-1]) == 1:
        return tuple(parts[:-1]), parts[-1]
    return None


def _same_person(full, abbrev):
    surname, initial = abbrev
    book = _tokens_of(full)
    if not book or not surname or len(book) < len(surname):
        return False
    n = len(surname)
    if not any(tuple(book[i:i + n]) == surname for i in range(len(book) - n + 1)):
        return False
    return book[0][:1] == initial


def abbrev_rows(sport_id):
    """Store rows whose participants are printed in the abbreviated form."""
    out = []
    for r in results_store.load(sport_id):
        h, a = abbreviated(r.get("home")), abbreviated(r.get("away"))
        if h and a:
            out.append((r["date"], h, a, r["home_score"], r["away_score"]))
    return out


def lookup_abbrev(rows, home, away, start, tolerance_days=1, elapsed_hours=None):
    """Scan abbreviated rows for this fixture, either way round. The LAST route tried.

    Deliberately last: it is the weakest identification here, so it may only answer where
    the book's own ids and an exact name have both failed, never override them.
    """
    hits = []
    for date, h, a, hs, as_ in rows:
        if _same_person(home, h) and _same_person(away, a):
            hits.append((date, hs, as_))
        elif _same_person(home, a) and _same_person(away, h):
            hits.append((date, as_, hs))
    return _nearest(hits, start, tolerance_days, elapsed_hours)


def lookup_by_id(table, home_id, away_id, start, tolerance_days=1, elapsed_hours=None):
    """The exact match: same two participants, as the book numbers them, near that date.

    The date check stays even here. An id pair identifies the PAIRING, not the fixture,
    and these circuits run the same two players against each other repeatedly — grading
    tonight's match from last week's meeting is precisely the bug that once produced a
    fake 87% hit rate.
    """
    if not (home_id and away_id):
        return None
    return _nearest(table.get((str(home_id), str(away_id))), start, tolerance_days,
                    elapsed_hours)


# The shortest a match of this sport can plausibly take, in hours. A fixture that started
# less than this ago has NOT finished, whatever some table says about the same two names.
#
# This guard exists because the alternative was caught doing real damage. Grading was
# routed through the results store and immediately settled "San Francisco Giants +2.5" as
# a WIN at 9-2, seventy-five minutes after a baseball game started — the score was the
# PREVIOUS DAY'S meeting of the same two teams, reachable through the one-day tolerance.
# One prediction, 100% hit rate, and a number that would have steered everything after it.
# It is the second time this project has produced a hit rate out of previous meetings.
MIN_HOURS = {
    1: 2.0,    # football
    2: 2.5,    # ice hockey
    3: 2.0,    # basketball
    4: 1.0,    # tennis
    5: 2.5,    # baseball
    6: 1.0,    # volleyball
    8: 1.5,    # handball
    10: 0.4,   # table tennis
    16: 0.5,   # badminton
    21: 1.0,   # darts
    30: 1.0,   # snooker
    40: 1.0,   # esports
    66: 3.0,   # cricket
}
DEFAULT_MIN_HOURS = 2.0

# Beyond that, an ADJACENT-day result may only answer for a fixture once this long has
# passed — long enough that the timezone gap is the only explanation left for a date that
# does not match, rather than "today's result simply is not in yet".
ADJACENT_AFTER_HOURS = 8.0


def _hours_since(start, now):
    """Hours between a fixture's start and now, or None if either cannot be read."""
    try:
        began = datetime.fromisoformat(str(start))
        current = datetime.fromisoformat(str(now))
    except (TypeError, ValueError):
        return None
    return (current - began).total_seconds() / 3600.0


def finished_enough(sport_id, start, now):
    """Has this fixture had time to finish? A grader that can score a running match will."""
    hours = _hours_since(start, now)
    if hours is None:
        return False
    return hours >= MIN_HOURS.get(sport_id, DEFAULT_MIN_HOURS)


def _nearest(entries, start, tolerance_days, elapsed_hours=None):
    """The entry for THIS fixture: same date first, an adjacent one only as a last resort.

    Same-date is preferred rather than merely allowed. Taking the first entry within
    tolerance meant an adjacent day could answer while the correct row was sitting further
    down the same list.
    """
    from datetime import date

    if not entries:
        return None
    want = (start or "")[:10]
    if not want:
        return None
    try:
        target = date.fromisoformat(want)
    except ValueError:
        return None
    best = None
    for when, hg, ag in entries:
        try:
            got = date.fromisoformat(when)
        except ValueError:
            continue
        gap = abs((got - target).days)
        if gap > tolerance_days:
            continue
        if gap == 0:
            return (hg, ag)
        if best is None or gap < best[0]:
            best = (gap, hg, ag)
    if best is None:
        return None
    # An adjacent day is the timezone gap OR yesterday's meeting of the same pair, and
    # nothing in the row distinguishes them. Only accept it once today's result has had
    # ample time to appear and has not.
    if elapsed_hours is not None and elapsed_hours < ADJACENT_AFTER_HOURS:
        return None
    return (best[1], best[2])


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
    # The store, per sport, loaded once for the sports actually waiting on it.
    sports = sorted({p.get("sport_id") for p in pending if p.get("sport_id")})
    store = {sid: store_results(sid) for sid in sports}
    abbrev = {sid: abbrev_rows(sid) for sid in sports}
    print(f"result rows available: store "
          f"{ {sid: len(n) for sid, (_i, n) in sorted(store.items())} }, "
          f"football-data {len(results_fb)}, tt collector {len(results_tt)}")

    now = datetime.now(timezone.utc).isoformat()
    newly = skipped_future = still_running = 0
    by_route = defaultdict(int)
    for p in pending:
        # A fixture that has not started cannot have a result, and one that started ten
        # minutes ago has not finished either. Both guards, because a grader that CAN
        # score a running match is a grader that eventually will — and it already did,
        # settling a baseball selection from the previous day's meeting of the same two
        # teams seventy-five minutes after first pitch.
        if (p.get("start") or "") > now:
            skipped_future += 1
            continue
        if not finished_enough(p.get("sport_id"), p.get("start"), now):
            still_running += 1
            continue
        elapsed = _hours_since(p.get("start"), now)
        by_id, by_name = store.get(p.get("sport_id")) or ({}, {})
        # Exact first: the same two participants as the book numbers them.
        score = lookup_by_id(by_id, p.get("p1_id"), p.get("p2_id"), p.get("start"),
                             elapsed_hours=elapsed)
        route = "id"
        if not score:
            score = lookup_result(by_name, p.get("p1"), p.get("p2"), p.get("start"),
                                  elapsed_hours=elapsed)
            route = "store name"
        if not score:
            table = results_fb if p.get("sport_id") == 1 else results_tt
            score = lookup_result(table, p.get("p1"), p.get("p2"), p.get("start"),
                                  elapsed_hours=elapsed)
            route = "football-data" if p.get("sport_id") == 1 else "tt collector"
        if not score:
            # Last, and weakest: a source that prints "Fritz T." where the book prints
            # "Taylor Harry Fritz". Only reached once the ids and the exact name have
            # both failed, so it can never overrule a stronger identification.
            score = lookup_abbrev(abbrev.get(p.get("sport_id")) or [], p.get("p1"),
                                  p.get("p2"), p.get("start"), elapsed_hours=elapsed)
            route = "abbrev name"
        if not score:
            continue
        row = {"market_key": (0, p["market_line"]), "outcome_id": p.get("outcome_id")}
        outcome = grade.settle(row, score[0], score[1])
        if outcome is None:
            # An unsupported market must stay pending rather than be scored on a guess.
            continue
        # Counted only once the market actually settled, so the routes reported add up to
        # the number graded rather than to the number matched.
        by_route[route] += 1
        p["result"] = outcome
        p["final_score"] = list(score)
        p["graded_via"] = route
        p["graded_at"] = datetime.now(timezone.utc).isoformat()
        newly += 1

    if newly:
        write_jsonl(args.predictions, preds)
    print(f"newly graded: {newly} | not started yet: {skipped_future} | "
          f"still being played: {still_running}")
    if by_route:
        # Which route settled what. Worth printing: if the exact id match ever stops
        # carrying most of them, something upstream has quietly broken.
        print("  " + " · ".join(f"{k}: {v}" for k, v in sorted(by_route.items())))

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
