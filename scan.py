#!/usr/bin/env python3
"""Betwinner odds scanner — single book, composite score, top-N singles.

Usage:
  python scan.py --input fixtures/sample.json
  python scan.py --input data/betwinner_34480.json --top 50
  python scan.py --input fixtures/sample.json --include-alt --parlay

Runs fully offline on a saved JSON pull. Fetching is done by GitHub Actions
(the operator's machine blocks the site). See README.md.
"""
import argparse
import json
import sys

import config
from engine import parser, score, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to an odds-by-tournaments JSON pull")
    ap.add_argument("--book", default=config.BOOK, help="Bookmaker slug to scan")
    ap.add_argument("--top", type=int, default=config.TOP_N)
    ap.add_argument("--include-alt", action="store_true", help="Include alternative lines")
    ap.add_argument("--parlay", action="store_true", help="Also print a top-N parlay summary")
    args = ap.parse_args()

    if args.include_alt:
        config.INCLUDE_ALT_LINES = True

    try:
        with open(args.input) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Unexpected payload: expected a list of fixtures.", file=sys.stderr)
        sys.exit(1)

    found = parser.books_in(data)
    report.warn_book(args.book, found)

    rows = parser.normalize(data, args.book)
    if not rows:
        print(f"No selections for book '{args.book}' in this file. "
              f"Books present: {', '.join(sorted(found)) or '<none>'}")
        sys.exit(0)

    scored = score.filter_and_score(rows)
    print(f"\nBook: {args.book} | fixtures: {len(data)} | "
          f"selections parsed: {len(rows)} | passed filters: {len(scored)}\n")

    report.print_table(scored, args.top)
    report.write_json(scored, args.top, config.REPORT_PATH)

    if args.parlay:
        report.parlay_summary(scored, args.top)


if __name__ == "__main__":
    main()
