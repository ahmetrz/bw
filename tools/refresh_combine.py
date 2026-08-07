#!/usr/bin/env python3
"""Rebuild today's combine bet-slip code from legs that have NOT started.

    python tools/refresh_combine.py --input combine.json

WHY THE CODE CANNOT BE MINTED ONCE A DAY. A bet slip is not a document, it is a live
object: the moment one of its legs kicks off the book REBUILDS the slip without it, and
the rebuild takes the default bet type. Measured on the old singles-list product — five
live legs saved as singles read back as singles; the same five plus one started fixture
read back `Vid=1` with a combined coefficient and `HasRemoveEvents` true. So the code
minted when the combine was built is correct at that moment and wrong by the time anyone
opens it. Codes also expire outright: every one from three days ago now answers
"Incorrect code". docs/DECISIONS/0007 carries this mechanism over from the retired daily
picks product (tools/refresh_coupon.py) unchanged in principle — only the input shape
(combine.json's flat leg list, not a windowed picks report) is different.

It never adds a leg and never reorders one. It takes the day's combine, drops what has
already begun, and asks the book for a slip of the rest. Run hourly, alongside grading
(results.yml) — a separate concern from tools/daily_combine.py, which only ever mints the
FIRST code, before any leg could plausibly have started yet.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import coupon  # noqa: E402

# A leg this close to kick-off is treated as gone. The book suspends a market before the
# whistle rather than at it, and a slip refused for one late leg is worse than one leg
# short.
MARGIN_MINUTES = 12


def open_legs(combine, now=None):
    """Today's combine legs, minus anything already under way. Order is left alone."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now + timedelta(minutes=MARGIN_MINUTES)).isoformat()
    out = []
    for leg in combine.get("legs") or []:
        if not leg.get("_game_id") or leg.get("_outcome_id") is None or not leg.get("_market_key"):
            continue
        if (leg.get("start") or "") <= cutoff:
            continue
        out.append({"game_id": leg["_game_id"], "outcome_id": leg["_outcome_id"],
                    "odds": leg["odds"], "market_key": tuple(leg["_market_key"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="combine.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"{args.input} yok — yenilenecek kupon da yok")
        return 0
    with open(args.input) as f:
        combine = json.load(f)

    total = len(combine.get("legs") or [])
    if not total:
        print("bugün kombine yok — yenilenecek kupon da yok")
        return 0

    legs = open_legs(combine)
    if not legs:
        # Everything has started. Say so rather than leaving a dead code on the page: a
        # five-character code that loads nothing is worse than no code.
        print(f"kombinin tamamı başlamış ({total} bacak tarandı) — kod kaldırılıyor")
        combine["coupon_code"] = None
        combine["coupon_detail"] = ""
        if not args.dry_run:
            with open(args.input, "w") as f:
                json.dump(combine, f, indent=2, ensure_ascii=False)
        return 0

    code, detail = coupon.create(legs)
    print(f"kupon: {code or '—'} ({detail}) · başlamamış {len(legs)}/{total} bacaktan")
    if not code:
        return 0                    # refused for a stated reason; leave the file alone
    if args.dry_run:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
    combine["coupon_code"] = code
    combine["coupon_detail"] = f"{detail} · {stamp} itibarıyla"
    with open(args.input, "w") as f:
        json.dump(combine, f, indent=2, ensure_ascii=False)
    print(f"{args.input} yeniden yazıldı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
