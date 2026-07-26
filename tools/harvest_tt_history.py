#!/usr/bin/env python3
"""Harvest table-tennis head-to-head history from Setka, for calibration.

    python tools/harvest_tt_history.py --pairs 300

The scoreboard endpoint is a rolling ~19-match window, so results could only be
accumulated by polling — a month of waiting before anything could be calibrated. The
compare endpoint changes that completely: /Players/{lang}/compare?player1Id=X&player2Id=Y
returns the FULL head-to-head archive for a pair, finished matches with set scores and a
winner, going back to 2021. One call can return ninety matches.

It was found by reading the site's own JS bundle, which named the route; the parameter
names took a few tries, and the endpoint returns an empty envelope rather than an error
when they are wrong — a 200 that looks like "no data" and actually means "wrong query".

Pairs are taken from the upcoming card, which is the right population by construction:
those are the players we will be asked to price.

Append-only and deduplicated on match id, so re-running only adds what is new.
"""
import argparse
import itertools
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import setka  # noqa: E402

BASE = "https://tabletennis.setkacup.com/api"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")


def compare(p1, p2, timeout=25):
    """Full head-to-head archive for one pair."""
    url = f"{BASE}/Players/1/compare?player1Id={p1}&player2Id={p2}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    return body.get("matches") or []


def normalize(m):
    """One archive record -> the fields calibration needs, or None if not gradeable."""
    if m.get("statusId") != setka.STATUS_FINISHED or m.get("technicalResult"):
        return None
    winner = m.get("winner") or {}
    p1, p2 = m.get("player1") or {}, m.get("player2") or {}
    if not winner.get("id") or not p1.get("id") or not p2.get("id"):
        return None
    try:
        s1, s2 = int(m.get("player1Score")), int(m.get("player2Score"))
    except (TypeError, ValueError):
        return None
    return {
        "match_id": m.get("id"),
        "start": m.get("startDate"),
        "tournament": m.get("tournamentName"),
        "p1_id": p1["id"], "p2_id": p2["id"],
        "p1_name": f"{p1.get('firstName','')} {p1.get('lastName','')}".strip(),
        "p2_name": f"{p2.get('firstName','')} {p2.get('lastName','')}".strip(),
        "sets": [s1, s2],
        "p1_won": winner["id"] == p1["id"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/tt_history.jsonl")
    ap.add_argument("--pairs", type=int, default=300)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    seen = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["match_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    before = len(seen)

    fixtures = setka.nearest()
    pairs = []
    players = []
    for m in fixtures:
        a, b = m.get("player1Id"), m.get("player2Id")
        if a and b:
            pairs.append((a, b))
            players += [a, b]
    # Beyond the scheduled pairings, cross-pair the same player pool: these players face
    # each other constantly on these circuits, so most combinations have real history and
    # each one that does multiplies the calibration set.
    pool = list(dict.fromkeys(players))
    extra = [p for p in itertools.combinations(pool, 2) if p not in set(pairs)]
    pairs = (pairs + extra)[: args.pairs]
    print(f"upcoming fixtures: {len(fixtures)} | player pool: {len(pool)} | "
          f"pairs to query: {len(pairs)}")

    executor = ThreadPoolExecutor(max_workers=args.workers)
    added = 0
    with open(args.out, "a") as f:
        for matches in executor.map(lambda p: compare(p[0], p[1]), pairs):
            for raw in matches:
                rec = normalize(raw)
                if not rec or rec["match_id"] in seen:
                    continue
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                seen.add(rec["match_id"])
                added += 1

    print(f"harvested: {added} new matches, {len(seen)} total (was {before})")
    if seen:
        with open(args.out) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        dates = sorted(r["start"] for r in rows if r.get("start"))
        who = {r["p1_id"] for r in rows} | {r["p2_id"] for r in rows}
        if dates:
            print(f"span: {dates[0][:10]} -> {dates[-1][:10]} | {len(who)} distinct players")
    return 0


if __name__ == "__main__":
    sys.exit(main())
