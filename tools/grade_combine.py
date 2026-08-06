#!/usr/bin/env python3
"""Settle graded combines: fill in data/combine_log.jsonl's `settlement` field once every
leg's result is known.

    python tools/grade_combine.py

Reuses tools/grade_predictions.py's result-lookup machinery WHOLESALE (store_results,
lookup_by_id, lookup_result, abbrev_rows, lookup_abbrev, finished_enough) rather than
re-deriving a second copy of "how do we find out who won" — that logic already carries
the hard-won guards (date tolerance, adjacent-day guard, id-before-name priority) this
grader needs exactly as much as the singles grader does, and a second implementation is a
second chance to reintroduce a bug those guards were written to fix.

A combine settles only once EVERY leg has an individual result — a leg still pending
leaves the whole day's combine pending, never partially graded.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import combine, grade  # noqa: E402
from tools import grade_predictions as gp  # noqa: E402

DEFAULT_LOG = "data/combine_log.jsonl"


def _grade_leg(leg, stores, abbrevs, now_iso):
    """One leg's WIN/LOSS/PUSH/HALF, or None if it cannot be settled yet/at all."""
    sport_id = leg.get("sport_id")
    start = leg.get("start")
    if (start or "") > now_iso:
        return None, "not_started"
    if not gp.finished_enough(sport_id, start, now_iso):
        return None, "in_progress"
    elapsed = gp._hours_since(start, now_iso)
    by_id, by_name = stores.get(sport_id) or ({}, {})
    score = gp.lookup_by_id(by_id, leg.get("p1_id"), leg.get("p2_id"), start,
                            elapsed_hours=elapsed)
    route = "id"
    if not score:
        score = gp.lookup_result(by_name, leg.get("p1"), leg.get("p2"), start,
                                 elapsed_hours=elapsed)
        route = "store name"
    if not score:
        score = gp.lookup_abbrev(abbrevs.get(sport_id) or [], leg.get("p1"), leg.get("p2"),
                                 start, elapsed_hours=elapsed)
        route = "abbrev name"
    if not score:
        return None, "no_result_yet"
    mk = leg.get("_market_key")
    if not mk:
        return None, "no_market_key"
    row = {"market_key": tuple(mk), "outcome_id": leg.get("_outcome_id")}
    outcome = grade.settle(row, score[0], score[1])
    if outcome is None:
        return None, "unsupported_market"
    return {"result": outcome, "odds": leg.get("odds"), "final_score": list(score),
           "graded_via": route}, "graded"


def grade_all(path=DEFAULT_LOG, now=None):
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    if not os.path.exists(path):
        print(f"{path} does not exist yet — nothing to grade")
        return 0
    rows = gp.load_jsonl(path)
    pending = [r for r in rows if r.get("settlement") is None]
    print(f"combines: {len(rows)} total, {len(pending)} unsettled")

    sports = sorted({leg.get("sport_id") for r in pending for leg in (r.get("legs") or [])})
    stores = {sid: gp.store_results(sid) for sid in sports}
    abbrevs = {sid: gp.abbrev_rows(sid) for sid in sports}

    settled = 0
    for r in pending:
        legs = r.get("legs") or []
        if not legs:
            # No combine that day — settled trivially, nothing to wait on.
            r["settlement"] = {"result": "no_bet", "multiplier": None,
                              "needs_confirmation": False}
            settled += 1
            continue
        graded_legs, statuses = [], []
        for leg in legs:
            g, status = _grade_leg(leg, stores, abbrevs, now_iso)
            statuses.append(status)
            if g:
                graded_legs.append(g)
                leg["result"] = g["result"]
                leg["final_score"] = g["final_score"]
                leg["graded_via"] = g["graded_via"]
        if len(graded_legs) < len(legs):
            continue   # at least one leg still pending — the whole combine stays pending
        r["settlement"] = combine.settle_combine(graded_legs)
        settled += 1
        print(f"  {r.get('date')}: {r['settlement']['result']} "
              f"(x{r['settlement']['multiplier']})" if r['settlement']['multiplier']
              else f"  {r.get('date')}: {r['settlement']['result']}")

    if settled:
        gp.write_jsonl(path, rows)
    print(f"newly settled: {settled}")
    return 0


if __name__ == "__main__":
    sys.exit(grade_all())
