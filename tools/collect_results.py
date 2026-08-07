#!/usr/bin/env python3
"""Collect finished results into data/results/<sport>.jsonl, one adapter per source.

    python tools/collect_results.py --list
    python tools/collect_results.py --all
    python tools/collect_results.py --source tml

AN ADAPTER'S ENTIRE JOB is to yield {date, home, away, home_score, away_score}. It owns no
maths, no model, no probability and no calibration — engine/model_generic.py does all of
that for every sport identically. That is the point of the split: adding a sport used to
mean a harvester AND a model AND a probability function AND a calibration, three of which
were also three fresh chances to be wrong. Now it means one function like the ones below.

Every adapter declares the ROBOTS check that was actually performed, by our crawler's
name, with the date. A source recorded as verified has twice become disallowed since this
project started — FIVB, then cbv.com.br — so the check belongs next to the code that
fetches, where it will be read, and not only in a research file.

FOOTBALL AND TENNIS ONLY (docs/DECISIONS/0007). Adapters for basketball (EuroLeague),
baseball (MLB) and table tennis (Setka) existed here and are gone, not merely unused —
the product's scope narrowed to the two sports engine/combine.py ever prices, and a
collector for a sport nothing reads is dead weight with a robots.txt check that will
silently rot. Their old result files under data/results/ were left as a historical record
rather than deleted; only the active collection code went.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import results_store  # noqa: E402

UA = "bw-scanner/1.0 (result collection for a personal betting model; contact via repo)"


def fetch(url, timeout=45, tries=3, accept="application/json"):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1.5 * (attempt + 1))
    return None


# --------------------------------------------------------------- football (sport 1)

FD_BASE = "https://www.football-data.co.uk/mmz4281"
FD_DIVS = ("E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2",
           "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1")
FD_EXTRA = ("ARG", "AUT", "BRA", "CHN", "DNK", "FIN", "IRL", "JPN", "MEX", "NOR",
            "POL", "ROU", "RUS", "SWE", "SWZ", "USA")


def football(seasons=("1617", "1718", "1819", "1920", "2021", "2122", "2223",
                      "2324", "2425", "2526")):
    """football-data.co.uk season CSVs — the same source the grader already settles on.

    robots.txt checked 2026-07-26 for ClaudeBot and anthropic-ai: neither is named and
    there is no wildcard Disallow.
    """
    for season in seasons:
        for div in FD_DIVS:
            raw = fetch(f"{FD_BASE}/{season}/{div}.csv", accept="text/csv")
            if not raw:
                continue
            for rec in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
                if not rec.get("HomeTeam") or rec.get("FTHG") in (None, ""):
                    continue
                yield {
                    "date": _fd_date(rec.get("Date")),
                    "home": rec["HomeTeam"], "away": rec.get("AwayTeam"),
                    "home_score": rec.get("FTHG"), "away_score": rec.get("FTAG"),
                    "league": div, "pool": div, "season": season,
                    "unit": "goals", "source": "football-data",
                }
            time.sleep(0.2)
    for country in FD_EXTRA:
        raw = fetch(f"https://www.football-data.co.uk/new/{country}.csv", accept="text/csv")
        if not raw:
            continue
        for rec in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
            if not rec.get("Home") or rec.get("HG") in (None, ""):
                continue
            yield {
                "date": _fd_date(rec.get("Date")),
                "home": rec["Home"], "away": rec.get("Away"),
                "home_score": rec.get("HG"), "away_score": rec.get("AG"),
                "league": f"{country}:{rec.get('League') or ''}".strip(":"),
                "pool": f"{country}:{rec.get('League') or ''}".strip(":"),
                "season": rec.get("Season"), "unit": "goals", "source": "football-data",
            }
        time.sleep(0.2)


def _fd_date(raw):
    """dd/mm/yy or dd/mm/yyyy -> yyyy-mm-dd. A date we cannot read is not a date."""
    if not raw:
        return None
    parts = str(raw).strip().split("/")
    if len(parts) != 3:
        return None
    d, m, y = parts
    y = f"20{y}" if len(y) == 2 else y
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


# ----------------------------------------------------------------- tennis (sport 4)

TML = "https://raw.githubusercontent.com/Tennismylife/TML-Database/master/{year}.csv"


def _sets_from_score(text):
    """(winner sets, loser sets) from an ATP score string, or None.

    "6-2 6-1" -> (2, 0). "7-6(5) 4-6 6-3" -> (2, 1). A retirement, walkover or default
    returns None: the match did not run its course, so it is not a result about who is
    better at winning sets, and feeding it to the model would teach it that the stronger
    player sometimes loses in one.
    """
    if not text:
        return None
    low = str(text).lower()
    if any(w in low for w in ("ret", "w/o", "walkover", "def", "abd", "abandoned")):
        return None
    w = l = 0
    for chunk in str(text).split():
        chunk = chunk.split("(")[0]
        if "-" not in chunk:
            continue
        a, _, b = chunk.partition("-")
        try:
            a, b = int(a), int(b)
        except ValueError:
            continue
        if a > b:
            w += 1
        elif b > a:
            l += 1
    return (w, l) if w + l else None


def tennis(start=2015, end=2026):
    """Tennismylife's TML-Database on raw.githubusercontent.com — one CSV per year of ATP
    main-tour and challenger matches, with the set-by-set score.

    robots.txt on raw.githubusercontent.com: 404, so nothing is disallowed (checked
    2026-07-26). Jeff Sackmann's archive was the obvious alternative and is NOT used: it
    is CC BY-NC-SA, and this is a betting model, so the non-commercial clause is a real
    question rather than a formality.

    THE ORIENTATION MATTERS AND IT IS NOT OBVIOUS. This source lists the WINNER first, so
    emitting it as-is makes "home" the winner of every single match: the model then learns
    that the home side always wins, the expected margin never goes negative, and the whole
    thing fails its calibration — which is exactly what happened on the first run, at
    0.038. The two players are therefore ordered by their player id, which is decided
    before the match and cannot know who won.

    There is no home advantage on tour, so every row is marked neutral and the model's
    home term is switched off for tennis entirely.
    """
    for year in range(start, end + 1):
        raw = fetch(TML.format(year=year), accept="text/csv")
        if not raw:
            continue
        for rec in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
            sets = _sets_from_score(rec.get("score"))
            if not sets or not rec.get("winner_name") or not rec.get("loser_name"):
                continue
            date = str(rec.get("tourney_date") or "")
            if len(date) != 8 or not date.isdigit():
                continue
            win = (rec["winner_name"], rec.get("winner_id") or rec["winner_name"], sets[0])
            los = (rec["loser_name"], rec.get("loser_id") or rec["loser_name"], sets[1])
            first, second = sorted((win, los), key=lambda x: str(x[1]))
            yield {
                "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                "home": first[0], "away": second[0],
                "home_id": first[1], "away_id": second[1],
                "home_score": first[2], "away_score": second[2],
                # best-of-3 and best-of-5 are DIFFERENT GAMES for a set handicap: a Bo5
                # match can finish 3-0 and a Bo3 one cannot, and "+2.5 sets" therefore
                # means "wins a set" in one format and something else in the other. Pooled
                # together they failed calibration; kept apart each is measured on its own
                # matches, and the appearance floor refuses whoever has too few of them.
                "pool": f"bo{rec.get('best_of') or 3}",
                "league": rec.get("tourney_name"), "season": year,
                "neutral": True,          # no home court on tour
                "unit": "sets", "source": "tml",
                # TML mirrors Sackmann's column layout and has carried `surface` in every
                # year checked (2024 spot-checked directly: "Hard","Clay","Grass"). Stored
                # but NOT yet used to partition rating pools (see docs/TENNIS_MODELS.md) —
                # tennisexplorer, the other tennis source, cannot supply it, so partitioning
                # ratings by surface today would split a player's history between a
                # surface-labelled TML pool and an unlabelled tennisexplorer pool with no
                # way to reconcile the two. Recorded now so it is there the day that's fixed
                # instead of requiring the archive to be re-walked for a column that was
                # always in it.
                "surface": rec.get("surface") or None,
            }
        time.sleep(0.3)


# ------------------------------------------------------- tennis, current (sport 4)

TE_DAY = "https://www.tennisexplorer.com/results/?type=all&year={y}&month={m}&day={d}"

# One finished match is two <tr> rows sharing an id: "r10" then "r10b". Each carries the
# player's link, then <td class="result"> — the SETS won, which is exactly the unit this
# sport is scored in — then the games in each set, which we do not need.
_TE_PAIR = re.compile(r'<tr id="r(\d+)"[^>]*>(.*?)</tr>\s*<tr id="r\1b"[^>]*>(.*?)</tr>',
                      re.S)
_TE_NAME = re.compile(r'<td class="t-name"><a href="/player/([^/"]+)/">([^<]+)</a>')
_TE_SETS = re.compile(r'<td class="result">(\d+|&nbsp;|)</td>')


def _te_side(html):
    name, sets = _TE_NAME.search(html), _TE_SETS.search(html)
    if not (name and sets) or not sets.group(1).strip().isdigit():
        return None                        # unfinished, retired or a header row
    return name.group(2).strip(), name.group(1).strip(), int(sets.group(1))


def tennis_current(days=7, today=None):
    """tennisexplorer.com's day pages — the CURRENT results the archive does not have.

    Why a second tennis source. TML is the archive and it is six months behind: its 2026
    file ends on 17 January with 137 matches in it, so this week's ATP Washington is not
    in it and will not be. The live watcher cannot cover for that either, because the book
    publishes no format note for tennis. Without this the sport has no source at all and
    every tennis prediction stays pending for ever.

    robots.txt checked by our crawler's name, 2026-07-28: `User-agent: *` disallows only
    /redirect/, /terms-of-use/ and /contact/. Results pages are allowed. Qualified on the
    BODY as hard rule 10 demands, not on the 200: a real page is ~730 KB and parses to 599
    matches with per-set scores, and it is not a challenge page or a placeholder.

    Sources checked at the same time and REFUSED: worldfootball.net and atptour.com both
    name ClaudeBot with `Disallow: /`; sofascore.com, api.sofascore.com, besoccer.com and
    footballdatabase.eu answer 403/406 to robots.txt itself, so the question of permission
    never arises. thesportsdb.com allows crawling but sends `Content-Signal: ai-input=no`,
    which is exactly what this would be, so it is not used either.

    NAMES ARE ABBREVIATED — "Fritz T." where the book says "Taylor Harry Fritz". They are
    emitted as printed rather than guessed at; `grade_predictions.lookup_abbrev` is the
    bridge, and it is the LAST route tried so a weaker identification never displaces the
    book's own ids.
    """
    from datetime import date, timedelta
    end = today or date.today()
    for back in range(days):
        d = end - timedelta(days=back)
        raw = fetch(TE_DAY.format(y=d.year, m=f"{d.month:02d}", d=f"{d.day:02d}"),
                    accept="text/html")
        if not raw:
            continue
        body = raw.decode("utf-8", "replace")
        for m in _TE_PAIR.finditer(body):
            a, b = _te_side(m.group(2)), _te_side(m.group(3))
            if not a or not b or a[2] == b[2]:
                continue                   # a tennis match cannot end level
            yield {
                "date": d.strftime("%Y-%m-%d"),
                "home": a[0], "away": b[0],
                "home_id": a[1], "away_id": b[1],   # the site's player slug, stable
                "home_score": a[2], "away_score": b[2],
                # Best-of-three and best-of-five are different bets for a set handicap, so
                # they are different pools. The SCORE says which: nothing best-of-three
                # reaches three sets, and that holds whoever is playing.
                "pool": "bo5" if max(a[2], b[2]) >= 3 else "bo3",
                "neutral": True,           # no home court on tour
                "unit": "sets", "source": "tennisexplorer",
            }
        time.sleep(1.0)                    # a small site; one page a second


ADAPTERS = {
    "football": (1, football),
    "tml": (4, tennis),
    "tennisexplorer": (4, tennis_current),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="one adapter name")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--restate", action="store_true",
                    help="re-apply this adapter's fields to the rows it already stored")
    args = ap.parse_args()

    if args.list or not (args.source or args.all):
        print("adapters:")
        for name, (sid, _fn) in sorted(ADAPTERS.items()):
            print(f"  {name:<12} -> sport {sid}")
        print("\nstored:")
        for sid, s in sorted(results_store.summary().items()):
            print(f"  sport {sid:<4} {s['games']:>7} games  {s['teams']:>5} teams  "
                  f"{s['first']} → {s['last']}  {', '.join(s['sources'])}")
        return 0

    names = [args.source] if args.source else sorted(ADAPTERS)
    for name in names:
        if name not in ADAPTERS:
            print(f"unknown adapter {name!r}", file=sys.stderr)
            continue
        sid, fn = ADAPTERS[name]
        if args.restate:
            # An adapter that learns to declare a new field leaves every row it wrote
            # BEFORE that without it, because merge keeps what is already stored and only
            # adds what is missing. That is the right default — a collector must never
            # rewrite history on a re-run — but it means `unit` and `pool` only ever
            # reached new rows. Restating re-derives the adapter's own rows and lets the
            # fresh version win, while leaving other sources' rows in the same file
            # untouched. The SCORE is not re-derived from anywhere new: it is the same
            # adapter reading the same source.
            added, total = results_store.restate(sid, fn())
            print(f"{name:<12} sport {sid}: {added} restated, {total} stored", flush=True)
            continue
        added, total = results_store.merge(sid, fn())
        print(f"{name:<12} sport {sid}: +{added} new, {total} stored", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
