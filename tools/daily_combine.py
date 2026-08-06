#!/usr/bin/env python3
"""The daily combine: ONE football+tennis combine a day, or an honest "none today".

    python tools/daily_combine.py --input data/betwinner_daily.json.gz

A SEPARATE product from tools/daily_report.py's top-N picks list (docs/DECISIONS/0001,
0003) — reuses the SAME already-fetched card and the SAME model loading
(tools/daily_report.load_models), so this never re-downloads anything, but applies its
own 80-point confidence floor, its own ten-judge referee board, and a genuine
multi-objective selection (engine/combine.py) instead of a top-N list.

Pipeline: fetch (reused) -> normalize (reused) -> restrict to football+tennis
  -> pick.for_fixtures() (reused, same models) -> settlement + confidence + data quality
  -> engine.referee (10 judges) -> engine.combine (beam search) -> coupon.create()
  -> data/combine_log.jsonl (immutable, one row per day) -> combine.json

Writes combine.json only; tools/make_platform_pages.py renders combine.html (and every
other new screen) from it in a separate step, the same separation of "produce data" from
"render every page" the platform brief's web-panel section implies by asking for 18
consistent screens rather than 18 independently-formatted ones.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import (bwfeed, combine, confidence, coupon, mirror, pick,  # noqa: E402
                    rating, settlement, track_record, tr)
from tools import daily_report  # noqa: E402

CONFIG_FINGERPRINT_KEYS = (
    "MIN_ODDS", "MIN_MODEL_SURVIVAL", "ALLOW_PUSH_MARKETS", "MIN_COMBINE_CONFIDENCE",
    "MIN_COMBINE_COMBINED_PROBABILITY", "COMBINE_BEAM_WIDTH", "COMBINE_MAX_LEAGUE_SHARE",
)


def config_fingerprint():
    """A short hash of the thresholds that shaped this run — section 23's "config hash"
    requirement. Not a full settings dump; just enough that two combines built under
    different thresholds are visibly NOT directly comparable."""
    payload = {}
    for k in CONFIG_FINGERPRINT_KEYS:
        v = getattr(config, k, None)
        payload[k] = sorted(v) if isinstance(v, (set, frozenset)) else v
    payload["combine_sports"] = sorted(config.COMBINE_SPORTS)
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def build_context(now):
    return {
        "market_history": track_record.market_history(now=now),
        "calibration_by_sport": track_record.calibration_by_sport(),
    }


def serialize_leg(p, host):
    """The public-facing shape of one leg for combine.json / combine.html — trims the
    pick dict to what the report actually needs, same discipline engine/report.py
    already applies to the scan output, rather than dumping every internal field."""
    from engine import parlay
    return {
        "sport": tr.sport(p.get("sport_id"), str(p.get("sport_id"))),
        "sport_id": p.get("sport_id"),
        "league": p.get("league"),
        "match": f"{p.get('p1')} v {p.get('p2')}",
        "p1": p.get("p1"), "p2": p.get("p2"),
        # The book's own participant ids — kept so tools/grade_combine.py can settle this
        # leg the same exact-match-first way tools/grade_predictions.py already does,
        # rather than falling straight to fuzzy name matching.
        "p1_id": p.get("p1_id"), "p2_id": p.get("p2_id"),
        "start": p.get("start"),
        "market_type": p.get("market_type"),
        "selection": p.get("selection"),
        "selection_tr": tr.pick(p),
        "odds": p.get("odds"),
        "settlement": p.get("settlement"),
        "confidence": p.get("_confidence"),
        "referee": p.get("_referee"),
        "url": parlay.betwinner_url(p, host),
        # kept for grading later — never shown as the headline number, only used to
        # reconstruct combine settlement once results are in
        "_market_key": list(p["market_key"]) if p.get("market_key") else None,
        "_outcome_id": p.get("outcome_id"),
        "_match_id": p.get("match_id", p.get("fixture_id")),
    }


def log_combine(record, path):
    """Append one row to data/combine_log.jsonl — one row PER DAY (the combine is a
    single object, unlike predictions.jsonl's one-row-per-selection), so a day's combine
    can be re-read exactly as it was generated, including every referee decision and
    every gate-excluded/vetoed candidate, without recomputation.

    The SELECTION fields (legs, odds, confidence, why) are written once and never
    touched again — same discipline as tools/daily_report.log_predictions: a record
    rewritten after the fact could quietly become "what we would have built," which
    defeats the point of a self-learning log. tools/grade_combine.py is still allowed to
    fill in the INITIALLY-NONE `settlement` field once results are known, exactly the way
    tools/grade_predictions.py fills in `result` on existing predictions.jsonl rows — a
    settlement outcome is not a selection, and withholding it forever would just move the
    self-deception from "the pick" to "whether it ever gets marked right or wrong."
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def logged_today(path, day=None):
    """Same backstop pattern as tools/daily_report.logged_today: the morning workflow
    fires up to three times (GitHub drops scheduled runs often enough that daily.yml
    already carries two backstops), and only the first is meant to build anything — a
    later run would hand a different combine from the one already announced, with a new
    slip code. Checked against the LOG, not against combine.json/the HTML pages, which
    any run rebuilds regardless."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in gp_load_jsonl(path):
        if row.get("date") == day:
            return True
    return False


def gp_load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--hours", type=float, default=config.DAILY_WINDOWS_HOURS[0])
    ap.add_argument("--out", default="combine.json")
    ap.add_argument("--log", default="data/combine_log.jsonl")
    ap.add_argument("--no-coupon", action="store_true")
    ap.add_argument("--only-if-new", action="store_true",
                    help="skip entirely when today's combine is already logged (for "
                         "backstop runs behind a schedule that may have fired already)")
    args = ap.parse_args()

    if args.only_if_new and logged_today(args.log):
        print("bugünün kombine kaydı zaten var — yedek koşu hiçbir şeyi yeniden yazmıyor")
        return 0

    data = daily_report.load(args.input)
    if not bwfeed.is_bwfeed(data):
        print("Input is not a Betwinner feed pull — refusing to proceed.", file=sys.stderr)
        return 1
    rows = bwfeed.normalize(data)
    print(f"normalized rows: {len(rows)}")

    elo_model, tt, generic, index, fake = daily_report.load_models(rows)

    windowed = daily_report.within(rows, args.hours)
    windowed = [r for r in windowed if r.get("sport_id") in config.COMBINE_SPORTS]
    if fake:
        windowed = [r for r in windowed
                    if (r.get("sport_id"), r.get("league")) not in fake]
    print(f"football+tennis rows in {args.hours:.0f}h window: {len(windowed)}")

    picks, skipped = pick.for_fixtures(rows=windowed, index=index, elo_model=elo_model,
                                       tt=tt, generic=generic)
    print(f"candidate picks: {len(picks)} (skipped: {skipped})")
    settlement.annotate(picks)
    rating.annotate(picks)          # scores + numbers 1..N, same as the daily-picks path
    confidence.annotate(picks)      # full ConfidencePrediction per pick, from that score

    now = datetime.now(timezone.utc)
    context = build_context(now)
    report = combine.build_combine(picks, now, context)
    print(f"eligible: {report.get('eligible_count', 0)} · "
          f"referee-approved: {report.get('referee_approved_count', 0)} · "
          f"final combine: {report['leg_count']} legs")
    print(f"why: {report['why']}")

    host, host_source = mirror.current(getattr(config, "REFERRAL_URL", None))
    coupon_code, coupon_detail = (None, "")
    if not args.no_coupon and report["legs"]:
        coupon_code, coupon_detail = coupon.create(report["legs"])
        print(f"kupon kodu: {coupon_code or '—'} ({coupon_detail})")

    public = dict(report)
    public["legs"] = [serialize_leg(p, host) for p in report["legs"]]
    public["config_fingerprint"] = config_fingerprint()
    public["coupon_code"] = coupon_code
    public["coupon_detail"] = coupon_detail
    public["link_host"] = host
    public["date"] = now.strftime("%Y-%m-%d")
    public["min_combine_confidence"] = config.MIN_COMBINE_CONFIDENCE
    public["scanned_matches"] = len({r.get("match_id", r["fixture_id"]) for r in windowed})
    # Filled in later by tools/grade_combine.py, once every leg's result is known — never
    # by this script, which only ever sees the card before kickoff.
    public["settlement"] = None

    with open(args.out, "w") as f:
        json.dump(public, f, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}")

    log_combine(public, args.log)
    print(f"appended to {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
