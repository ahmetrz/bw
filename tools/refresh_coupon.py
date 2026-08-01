#!/usr/bin/env python3
"""Rebuild the day's bet-slip code from fixtures that have NOT started, and republish.

    python tools/refresh_coupon.py --report daily_report.json --page picks.html

WHY THE CODE CANNOT BE MINTED ONCE A DAY. A bet slip is not a document, it is a live
object: the moment one of its fixtures kicks off the book REBUILDS the slip without it,
and the rebuild takes the default bet type. Measured — five live legs saved as singles
read back as singles; the same five plus one started fixture read back `Vid=1` with a
combined coefficient of 1.93 and `HasRemoveEvents` true. So the code minted with the
morning list is correct when it is minted and an accumulator by the time anyone opens it,
still wearing the label "20 tekli bahis" that was true hours earlier. Codes also expire
outright: every one from three days ago now answers "Incorrect code".

So the LIST is produced once a day, as the operator asked, and the CODE is refreshed on
the hour beside the grading. Those are different objects with different lifetimes and
treating them as one is what made the feature look broken.

It never adds a selection and never reorders one. It takes the day's plan, drops what has
already begun, and asks the book for a slip of the rest.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import coupon  # noqa: E402
from tools import make_picks_page  # noqa: E402

# A fixture this close to kick-off is treated as gone. The book suspends a market before
# the whistle rather than at it, and a slip refused for one late leg is worth less than a
# slip that is one selection shorter.
MARGIN_MINUTES = 12


def open_picks(report, now=None):
    """The day's plan, minus anything already under way. Order is left alone."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now + timedelta(minutes=MARGIN_MINUTES)).isoformat()
    windows = report.get("windows") or []
    if not windows:
        return []
    widest = max(windows, key=lambda w: w.get("hours") or 0)
    out = []
    for p in widest.get("picks") or []:
        if p.get("in_plan") is False:
            continue
        if not p.get("game_id") or not p.get("outcome_id"):
            continue
        if (p.get("start") or "") <= cutoff:
            continue
        out.append({"game_id": p["game_id"], "outcome_id": p["outcome_id"],
                    "odds": p["odds"], "market_key": tuple(p["market_key"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="daily_report.json")
    ap.add_argument("--page", default="picks.html")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print("günlük rapor yok — yenilenecek kupon da yok")
        return 0
    with open(args.report) as f:
        report = json.load(f)

    picks = open_picks(report)
    total = sum(len(w.get("picks") or []) for w in report.get("windows") or [])
    if not picks:
        # Everything has started. Say so on the page rather than leaving a dead code on it:
        # a five-character code that loads nothing is worse than no code.
        print(f"planın tamamı başlamış ({total} seçim tarandı) — kod kaldırılıyor")
        report["coupon_code"] = None
        report["coupon_detail"] = ""
        if not args.dry_run:
            make_picks_page.build(report, args.page)
        return 0

    code, detail = coupon.create(picks)
    print(f"kupon: {code or '—'} ({detail}) · başlamamış {len(picks)} seçimden")
    if not code:
        return 0                    # refused for a stated reason; leave the page alone
    if args.dry_run:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
    report["coupon_code"] = code
    report["coupon_detail"] = f"{detail} · {stamp} itibarıyla"
    make_picks_page.build(report, args.page)
    print(f"{args.page} yeniden yazıldı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
