#!/usr/bin/env python3
"""Harvest EuroLeague and EuroCup results into data/basketball_games.jsonl.

    python tools/harvest_basketball.py --from 2016 --to 2025

Source: api-live.euroleague.net/v2 — keyless JSON, and no robots.txt on that host or on
live.euroleague.net, so nothing here is disallowed. ESPN's APIs were the other obvious
candidate and are NOT used: www.espn.com/robots.txt names `anthropic-ai` with `Disallow: /`,
and the api subdomains only escape that by being separate hostnames. The intent is stated
plainly enough that reading it as permission would be reading it dishonestly.

What each game gives us, and why it matters for a basketball ladder:

  * final score, so the MARGIN — the handicap ladder is a margin question and nothing else
  * quarter partials, so regulation margin can be reconstructed
  * extraPeriods, so an overtime game is not mistaken for a two-point regulation win. The
    book settles full-game basketball INCLUDING overtime, and a model fitted on regulation
    margins would misprice exactly the close games where the handicap matters most.

Standard library only, like the rest of the project.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{comp}{year}/games"
UA = "bw-scanner/1.0 (basketball result collection; contact via repo)"

# E = EuroLeague, U = EuroCup. Both run the same schema.
COMPETITIONS = {"E": "EuroLeague", "U": "EuroCup"}


def fetch(url, timeout=45, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            if not body.strip():
                return None
            return json.loads(body.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):        # season not published
                return None
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            time.sleep(1.5 * (attempt + 1))
    return None


def games(comp, year):
    payload = fetch(BASE.format(comp=comp, year=year))
    if not payload:
        return []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def _side(entry):
    club = (entry or {}).get("club") or {}
    return club.get("name"), club.get("code"), (entry or {}).get("score")


def normalize(g, comp, year):
    """One finished game, or None. An unplayed or scoreless fixture is not a result."""
    if not g.get("played"):
        return None
    home, home_code, hs = _side(g.get("local"))
    away, away_code, as_ = _side(g.get("road"))
    if not (home and away) or hs is None or as_ is None:
        return None
    # A virtual club is a simulated entry, not a team that played a game.
    for entry in (g.get("local"), g.get("road")):
        if ((entry or {}).get("club") or {}).get("isVirtual"):
            return None

    partials = {}
    ot = 0
    for entry, key in ((g.get("local"), "home"), (g.get("road"), "away")):
        p = (entry or {}).get("partials") or {}
        partials[key] = [p.get(f"partials{i}") for i in range(1, 5)]
        extra = p.get("extraPeriods") or {}
        ot = max(ot, len([v for v in extra.values() if v is not None]))

    # Regulation margin, when all four quarters are published. Reconstructed rather than
    # assumed: a game that went to overtime has a regulation margin of exactly zero, and
    # that is the single most informative scoreline for a handicap model.
    reg = None
    if all(x is not None for x in partials["home"] + partials["away"]):
        reg = (sum(partials["home"]), sum(partials["away"]))

    return {
        "competition": COMPETITIONS.get(comp, comp),
        "season": year,
        "date": (g.get("date") or "")[:10],
        "round": g.get("round"),
        "home": home, "home_code": home_code,
        "away": away, "away_code": away_code,
        "home_score": hs, "away_score": as_,
        "margin": hs - as_,
        "regulation": list(reg) if reg else None,
        "overtimes": ot,
        "neutral": bool(g.get("isNeutralVenue")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=2016)
    ap.add_argument("--to", dest="end", type=int, default=2025)
    ap.add_argument("--out", default="data/basketball_games.jsonl")
    args = ap.parse_args()

    rows, seen = [], set()
    for comp in COMPETITIONS:
        for year in range(args.start, args.end + 1):
            raw = games(comp, year)
            kept = 0
            for g in raw:
                row = normalize(g, comp, year)
                if not row:
                    continue
                key = (row["competition"], row["season"], row["date"],
                       row["home"], row["away"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
                kept += 1
            print(f"{COMPETITIONS[comp]:<10} {year}: {len(raw):>4} fixtures -> {kept:>4} results",
                  flush=True)
            time.sleep(0.4)          # self-throttle; the host publishes no rate limit

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in sorted(rows, key=lambda x: (x["date"], x["home"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    teams = {r["home"] for r in rows} | {r["away"] for r in rows}
    ot = sum(1 for r in rows if r["overtimes"])
    print(f"\nwrote {args.out}: {len(rows)} games, {len(teams)} teams, "
          f"{ot} went to overtime ({100.0 * ot / max(1, len(rows)):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
