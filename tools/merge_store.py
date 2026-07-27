#!/usr/bin/env python3
"""Merge a saved copy of the results store back into the current one.

    python tools/merge_store.py /tmp/bwsave/results

WHY THIS EXISTS. Four workflows write to data/results on the same branch — the live
watcher four times a day, the table tennis collector every two hours, and the daily run.
When two land together the second one's `git pull --rebase` hits a conflict in a .jsonl
file, and the honest-looking fallback ("push failed, the next run will catch it") is
simply not true: the next run starts from origin/main on a fresh container, so the rows
that were collected and not pushed are gone, and a watched result cannot be re-watched —
the match is over.

So a losing run does not retry the rebase. It takes the remote state, replays its own rows
into it, and pushes that. `results_store.merge` is idempotent and keyed on the fixture, so
replaying rows that did make it through changes nothing, and rows that did not are added.
That is what the merge was built for.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import results_store  # noqa: E402
from tools import collect_live  # noqa: E402


def rows_of(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def merge_ledger(saved, live):
    """Union two append-only collection ledgers, keyed on (timestamp, sport).

    The ledger is what the daily report's "this sport is N days away" projection is
    computed from, and it was being dropped by the very recovery that saves the results:
    the retry path resets to the remote state, which does not have the lines this run
    appended. The results came back and the record of WHEN they arrived did not, so the
    measured rate would drift downwards every time a slice lost a race.
    """
    rows = {}
    for path in (live, saved):
        if not path or not os.path.exists(path):
            continue
        for r in rows_of(path):
            at, sport = r.get("at"), r.get("sport")
            if at is None or sport is None:
                continue
            rows[(at, sport)] = r
    if not rows:
        return 0
    with open(live, "w") as f:
        for key in sorted(rows):
            f.write(json.dumps(rows[key]) + "\n")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saved", help="directory holding <sport_id>.jsonl files")
    ap.add_argument("--ledger", default="", help="saved copy of data/watch_log.jsonl")
    args = ap.parse_args()

    if not os.path.isdir(args.saved):
        print(f"{args.saved} is not a directory", file=sys.stderr)
        return 1

    total = 0
    for name in sorted(os.listdir(args.saved)):
        if not name.endswith(".jsonl"):
            continue
        try:
            sport_id = int(name[:-6])
        except ValueError:
            continue
        added, held = results_store.merge(sport_id, rows_of(os.path.join(args.saved, name)))
        total += added
        if added:
            print(f"sport {sport_id}: +{added} replayed, {held} stored")
    if args.ledger:
        kept = merge_ledger(args.ledger, collect_live.LEDGER)
        print(f"ledger: {kept} entries after union")
    print(f"replayed {total} results that would otherwise have been lost")
    return 0


if __name__ == "__main__":
    sys.exit(main())
