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

PAIRS COME FROM THE WHOLE RATED POOL, NOT JUST TODAY'S FIXTURES, and that is the change
that made this useful. Drawing them from the current schedule only reached the few dozen
players in it: 7,465 matches accumulated across 88 distinct players, while Setka rates
2,007 and the book's card on one day carried 321. Coverage was not thin because the sport
is hard, it was thin because the crawl kept asking about the same people.

So the pool is every rated player, ordered by how much they play, and the pairs already
queried are REMEMBERED between runs in data/tt_pairs_seen.json. Each run spends its budget
on ground it has not covered, so running it on a schedule widens the archive instead of
re-reading it. Players on the upcoming card are queried first, because those are the ones
we will be asked to price today.

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


def _pair(a, b):
    """A pair is unordered — asking (A,B) and (B,A) would spend the budget twice."""
    return (a, b) if str(a) <= str(b) else (b, a)


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
    ap.add_argument("--memo", default="data/tt_pairs_seen.json",
                    help="pairs already queried; skipped on the next run")
    ap.add_argument("--pairs", type=int, default=1200)
    ap.add_argument("--pool", type=int, default=1200,
                    help="how many of the most active rated players to draw pairs from")
    ap.add_argument("--neighbours", type=int, default=8,
                    help="how many rating-adjacent opponents to query per player")
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

    asked = set()
    if os.path.exists(args.memo):
        try:
            with open(args.memo) as f:
                asked = {tuple(p) for p in json.load(f)}
        except (OSError, json.JSONDecodeError, TypeError):
            asked = set()

    # Today's fixtures first: those are the players we are about to be asked to price.
    fixtures = setka.nearest()
    pairs, on_card = [], []
    for m in fixtures:
        a, b = m.get("player1Id"), m.get("player2Id")
        if a and b:
            pairs.append(_pair(a, b))
            on_card += [a, b]

    # Then the wider rated pool, most active first. These circuits run the same players
    # against each other constantly, so most combinations have real history, and each one
    # that does multiplies the archive.
    rated = setka.ratings() or {}
    ranked = sorted(
        (pid for pid, p in rated.items() if (p.get("totalMatches") or 0) >= 30),
        key=lambda pid: -(rated[pid].get("totalMatches") or 0))
    try:
        ranked = [int(p) for p in ranked]
    except (TypeError, ValueError):
        pass
    pool = list(dict.fromkeys(on_card + ranked))[: args.pool]
    # Pair each player with their RATING NEIGHBOURS rather than enumerating combinations
    # in list order. Straight combinations spend the whole budget on the first few
    # players — 900 calls reached 43 of a 260-strong pool and the archive grew from 88
    # distinct players to 96. Neighbours are also who actually play each other on these
    # circuits, so a neighbour pair is far more likely to return real history than a
    # random one.
    by_rating = sorted(pool, key=lambda pid: -(rated.get(pid, {}).get("ratingSc") or 0)
                       if pid in rated else 0)
    for i, a in enumerate(by_rating):
        for b in by_rating[i + 1: i + 1 + args.neighbours]:
            pairs.append(_pair(a, b))

    fresh, dropped = [], 0
    for pr in dict.fromkeys(pairs):
        if pr in asked:
            dropped += 1
            continue
        fresh.append(pr)
        if len(fresh) >= args.pairs:
            break
    pairs = fresh
    print(f"upcoming fixtures: {len(fixtures)} | rated pool: {len(ranked)} "
          f"(using {len(pool)}) | already asked: {len(asked)} (skipped {dropped}) | "
          f"querying: {len(pairs)}")

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

    asked |= set(pairs)
    with open(args.memo, "w") as f:
        json.dump(sorted(asked), f)

    print(f"harvested: {added} new matches, {len(seen)} total (was {before}); "
          f"{len(asked)} pairs asked to date")
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
