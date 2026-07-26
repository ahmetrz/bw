#!/usr/bin/env python3
"""Settle a day's selections and rebuild the page as a scorecard.

    python tools/daily_results.py                    # the most recent logged day
    python tools/daily_results.py --date 2026-07-26

Runs after tools/grade_predictions.py has written results back into the prediction log.
Rebuilds the SAME page the morning list used, now with each selection marked KAZANDI /
KAYBETTİ / İADE and a hit-rate strip at the top, then notifies Telegram.

Built from data/predictions.jsonl rather than from daily_report.json, and that choice is
the point: the log is what was actually offered, written before the result was known and
never rewritten. Rebuilding the evening page from the morning report would let the two
drift; rebuilding it from the record cannot.

WHEN IT NOTIFIES — and why it is not simply "at midnight". Football results come from
football-data.co.uk, which publishes a few times a week, so a card played tonight is often
not gradeable until days later. A fixed nightly send would therefore deliver a mostly
empty scorecard and call it the day's result. Instead this sends when the settled count
for that day has GROWN since the last notification, and says plainly how many are still
pending. The operator hears about a day when there is actually something new to hear.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import grade, telegram  # noqa: E402
from tools import make_picks_page  # noqa: E402

STATE = "data/results_sent.json"


def load_log(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def as_report(day, rows):
    """Shape one day's logged predictions like a daily report, so the same page renders.

    The log stores the 48h card once, which is exactly the full list; there is no shorter
    window to reconstruct and inventing one would misreport when a bet was offered.
    """
    picks = []
    for r in sorted(rows, key=lambda x: (x.get("id") or 10 ** 6)):
        picks.append({
            "id": r.get("id"),
            "score": r.get("score"),
            "band": r.get("band"),
            "model_pct": r.get("model_pct"),
            "evidence_pct": r.get("evidence_pct"),
            "evidence_penalty": r.get("evidence_penalty"),
            "match": f"{r.get('p1')} v {r.get('p2')}",
            "p1": r.get("p1"), "p2": r.get("p2"),
            "league": r.get("league"),
            "start": r.get("start"),
            "sport_id": r.get("sport_id"),
            "selection": r.get("selection"),
            "selection_tr": r.get("selection_tr"),
            "odds": r.get("odds"),
            "model_survival": r.get("model_survival"),
            "settlement": r.get("settlement"),
            "url": r.get("url"),
            "result": r.get("result"),
            "final_score": r.get("final_score"),
        })
    graded = [p for p in rows if p.get("result")]
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "day": day,
        "heading": f"Betwinner {day} — sonuçlar",
        "min_odds": config.MIN_ODDS,
        "min_model_survival": config.MIN_MODEL_SURVIVAL,
        "summary": grade.summarize(graded),
        "windows": [{"hours": 48, "matches": len(rows), "skipped": {}, "picks": picks}],
    }


def build_notice(day, report, page_name, total, settled):
    s = report.get("summary") or {}
    decided = s.get("win", 0) + s.get("half", 0) + s.get("loss", 0)
    lines = [f"<b>📊 {day} sonuçları</b>", ""]
    if not s:
        lines += ["<i>Bu güne ait henüz sonuçlanan seçim yok.</i>"]
    else:
        hit = s.get("hit_rate")
        lines += [
            f"<b>{settled} / {total}</b> seçim sonuçlandı",
            f"✅ {s.get('win', 0)} kazandı · ❌ {s.get('loss', 0)} kaybetti · "
            f"↩️ {s.get('push', 0) + s.get('half', 0)} iade/yarım",
            (f"isabet <b>%{100 * hit:.1f}</b> ({decided} sonuçlanan üzerinden)"
             if hit is not None else "isabet: henüz hesaplanamıyor"),
            f"1 birimlik bahislerde getiri <b>{s['returned'] / s['staked']:.3f}x</b>"
            if s.get("staked") else "",
        ]
    pending = total - settled
    if pending:
        lines += ["", f"<i>{pending} seçim hâlâ bekliyor. Futbol sonuçları "
                      "football-data.co.uk'ten geliyor ve haftada birkaç kez "
                      "yayınlanıyor, bu yüzden aynı akşam tamamlanmayabilir — "
                      "sonuçlar geldikçe bu sayfa güncellenir.</i>"]
    lines += ["", f"📄 İşaretlenmiş tam liste ekteki <b>{page_name}</b> dosyasında."]
    return "\n".join(x for x in lines if x != "")


def read_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", default="data/predictions.jsonl")
    ap.add_argument("--date", default="", help="YYYY-MM-DD; blank = most recent logged day")
    ap.add_argument("--out", default="results.html")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--force-send", action="store_true",
                    help="notify even when nothing new was settled")
    args = ap.parse_args()

    log = load_log(args.predictions)
    if not log:
        print("no predictions logged yet", file=sys.stderr)
        return 0

    by_day = defaultdict(list)
    for r in log:
        by_day[r.get("date") or "?"].append(r)
    day = args.date or max(by_day)
    rows = by_day.get(day) or []
    if not rows:
        print(f"no predictions for {day}", file=sys.stderr)
        return 0

    settled = sum(1 for r in rows if r.get("result"))
    report = as_report(day, rows)
    n = make_picks_page.build(report, args.out)
    print(f"{day}: {settled}/{n} settled -> wrote {args.out}")
    s = report.get("summary")
    if s:
        print(f"  W {s['win']} · half {s['half']} · push {s['push']} · L {s['loss']} | "
              f"hit {s['hit_rate']:.1%}" if s.get("hit_rate") is not None else "  no decided legs")

    state = read_state(args.state)
    already = (state.get(day) or {}).get("settled", -1)
    if not args.force_send and settled <= already:
        print(f"nothing new since the last notification ({already} settled) — not sending")
        return 0
    if not settled:
        print("nothing settled yet — not sending")
        return 0

    notice = build_notice(day, report, os.path.basename(args.out), len(rows), settled)
    if args.no_telegram:
        print("\n--- notice preview ---\n")
        print(notice)
        return 0

    ok, detail = telegram.send_document(args.out, caption=notice, parse_mode="HTML")
    if not ok and telegram.configured():
        print(f"telegram document: NOT SENT — {detail}", file=sys.stderr)
        ok, detail = telegram.send(notice)
    print(f"telegram: {'OK' if ok else 'NOT SENT'} — {detail}")
    if ok:
        state[day] = {"settled": settled, "sent_at": datetime.now(timezone.utc).isoformat()}
        os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
        with open(args.state, "w") as f:
            json.dump(state, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
