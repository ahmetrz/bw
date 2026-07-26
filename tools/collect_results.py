#!/usr/bin/env python3
"""Collect finished results into data/results/<sport>.jsonl, one adapter per source.

    python tools/collect_results.py --list
    python tools/collect_results.py --all
    python tools/collect_results.py --source euroleague

AN ADAPTER'S ENTIRE JOB is to yield {date, home, away, home_score, away_score}. It owns no
maths, no model, no probability and no calibration — engine/model_generic.py does all of
that for every sport identically. That is the point of the split: adding a sport used to
mean a harvester AND a model AND a probability function AND a calibration, three of which
were also three fresh chances to be wrong. Now it means one function like the ones below.

Every adapter declares the ROBOTS check that was actually performed, by our crawler's
name, with the date. A source recorded as verified has twice become disallowed since this
project started — FIVB, then cbv.com.br — so the check belongs next to the code that
fetches, where it will be read, and not only in a research file.
"""
import argparse
import csv
import io
import json
import os
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


def football(seasons=("2324", "2425", "2526")):
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
                    "source": "football-data",
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
                "season": rec.get("Season"), "source": "football-data",
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


# ------------------------------------------------------------- basketball (sport 3)

EL_BASE = "https://api-live.euroleague.net/v2/competitions/{c}/seasons/{c}{y}/games"


def basketball(start=2007, end=2025):
    """EuroLeague + EuroCup. Keyless JSON; no robots.txt on api-live.euroleague.net
    (404), checked 2026-07-26. ESPN is deliberately NOT used: www.espn.com names
    anthropic-ai with Disallow: /, and its api subdomains only escape that by being
    separate hostnames."""
    for comp, name in (("E", "EuroLeague"), ("U", "EuroCup")):
        for year in range(start, end + 1):
            raw = fetch(EL_BASE.format(c=comp, y=year))
            if not raw:
                continue
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            for g in (payload.get("data") if isinstance(payload, dict) else payload) or []:
                if not g.get("played"):
                    continue
                loc, road = g.get("local") or {}, g.get("road") or {}
                lc, rc = loc.get("club") or {}, road.get("club") or {}
                if lc.get("isVirtual") or rc.get("isVirtual"):
                    continue
                yield {
                    "date": (g.get("date") or "")[:10],
                    "home": lc.get("name"), "away": rc.get("name"),
                    "home_score": loc.get("score"), "away_score": road.get("score"),
                    "home_id": lc.get("code"), "away_id": rc.get("code"),
                    "league": name, "season": year, "source": "euroleague",
                    "neutral": bool(g.get("isNeutralVenue")),
                }
            time.sleep(0.3)


# ----------------------------------------------------------- table tennis (sport 10)

def table_tennis(path="data/tt_results.jsonl"):
    """Whatever tools/collect_tt.py has accumulated from the Setka scoreboard.

    Setka's robots.txt allows everything (checked, Allow: /). The scoreboard is a rolling
    window rather than an archive, which is why a separate two-hourly workflow feeds it.
    """
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Setka stores the set tally as a two-element list, e.g. "sets": [1, 3].
            # It was first read as a list of per-set pairs, which raised on the very first
            # row — worth stating because it is the whole reason an adapter is this small:
            # a format mistake here fails loudly and costs nothing, instead of quietly
            # feeding a model.
            sets = r.get("sets")
            s1, s2 = r.get("p1_sets"), r.get("p2_sets")
            if s1 is None and isinstance(sets, (list, tuple)) and len(sets) == 2:
                s1, s2 = sets[0], sets[1]
            yield {
                "date": (r.get("date") or r.get("start") or "")[:10],
                "home": r.get("p1_name") or r.get("p1"),
                "away": r.get("p2_name") or r.get("p2"),
                "home_id": r.get("p1_id"), "away_id": r.get("p2_id"),
                "home_score": s1, "away_score": s2,
                "league": r.get("tournament") or "Setka", "source": "setka",
            }


ADAPTERS = {
    "football": (1, football),
    "euroleague": (3, basketball),
    "setka": (10, table_tennis),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="one adapter name")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
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
        added, total = results_store.merge(sid, fn())
        print(f"{name:<12} sport {sid}: +{added} new, {total} stored", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
