#!/usr/bin/env python3
"""Accumulate settled table-tennis results — the product's first feedback loop.

    python tools/collect_tt.py --out data/tt_results.jsonl

Why this exists at all: every model in this project has been unfalsifiable, because
nothing was ever compared against an outcome. PRODUCT_STATUS.md calls that the single
biggest architectural hole and it is right — without settled results there is no
backtest, no calibration, and no way to know when the product is wrong.

Setka's scoreboard is the first settled-results feed reachable for free, robots-permitted
and without a key. It is a ROLLING window of roughly 19 matches, not an archive, so the
history cannot be downloaded — it has to be built by polling. That is the whole job here:
append what is newly finished, never duplicate, never rewrite.

Append-only and deduplicated on the match id, so running it twice costs nothing and a
partial run loses nothing.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import setka  # noqa: E402


def load_seen(path):
    """Match ids already recorded. Reads line by line so one corrupt row cannot
    invalidate an entire accumulated history."""
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["match_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/tt_results.jsonl")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    seen = load_seen(args.out)
    before = len(seen)

    try:
        finished = setka.finished_matches()
    except Exception as e:
        print(f"setka unreachable: {e}", file=sys.stderr)
        return 0   # a source being down must not fail the daily run

    stamp = datetime.now(timezone.utc).isoformat()
    added = 0
    with open(args.out, "a") as f:
        for m in finished:
            if m["match_id"] in seen:
                continue
            m["collected"] = stamp
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
            seen.add(m["match_id"])
            added += 1

    print(f"table tennis results: {added} new, {len(seen)} total "
          f"(was {before}); {len(finished)} on the scoreboard now")

    # Report what the accumulated set can support yet, so the calibration gate is visible
    # rather than something to discover later.
    need = 400
    if len(seen) < need:
        print(f"calibration needs ~{need} settled matches; {need - len(seen)} to go")
    else:
        print("enough settled matches to calibrate the rating scale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
