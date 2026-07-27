#!/usr/bin/env python3
"""Say something when the daily list did NOT arrive.

    python tools/heartbeat.py                 # check today, notify if the day is missing
    python tools/heartbeat.py --dry-run

WHY THIS EXISTS. A workflow that does not run produces no failure to notice. On
2026-07-27 the daily schedule never fired — not late, not at all — and nothing said so;
the operator would simply have had no list that morning, and a missing list looks exactly
like a quiet card with no qualifying selections. The two are opposite situations and only
one of them needs a person.

So the check is not "did the job succeed" — a job that never started cannot report
anything about itself. It is "does today's OUTPUT exist", asked from outside by a
different schedule. The prediction log is the right thing to ask about: it is the one
artefact that cannot be reconstructed afterwards, so its absence is the failure that
actually costs something.

It notifies at most ONCE per day. An alarm that repeats every hour trains the operator to
ignore it, and this one only has to be believed the first time.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import telegram  # noqa: E402

STATE = "data/heartbeat.json"


def logged_days(path):
    """{date: number of predictions} from the permanent log."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                day = json.loads(line).get("date")
            except json.JSONDecodeError:
                continue
            if day:
                out[day] = out.get(day, 0) + 1
    return out


def verdict(days, today, now_hour, after_hour):
    """(ok, message). ok=True means there is nothing to say.

    Before `after_hour` the day is simply not due yet — the run has three scheduled
    chances and complaining at 07:00 about a 08:43 backstop would be noise.
    """
    if now_hour < after_hour:
        return True, f"{today}: henüz vakti değil (saat {now_hour:02d} UTC)"
    if days.get(today):
        return True, f"{today}: {days[today]} seçim kayıtlı, liste çıkmış"

    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    had = days.get(yesterday)
    # A day with no qualifying selection is a real and expected outcome, so the message
    # says what is KNOWN — no predictions were recorded — rather than asserting a failure
    # whose cause this check cannot see.
    msg = (f"⚠️ <b>{today} için günlük liste kaydedilmemiş.</b>\n\n"
           f"Bugün hiç tahmin kaydı yok. Bu ya günlük koşunun hiç çalışmadığı "
           f"anlamına gelir, ya da kartta güven eşiğini geçen tek bir seçim bile "
           f"çıkmadığı. İkisi farklı durumlar ve ayırt etmek için "
           f"<i>Actions &rsaquo; daily</i> koşularına bakmak gerekiyor.\n")
    if had:
        msg += f"\nKarşılaştırma: dün ({yesterday}) {had} seçim kaydedilmişti."
    msg += ("\n\nGünlük koşu 06:43, 07:43 ve 08:43 UTC'de üç kez deneniyor; üçü de "
            "kaçtıysa elle tetiklemek gerekiyor.")
    return False, msg


def read_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", default="data/predictions.jsonl")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--after-hour", type=int, default=9,
                    help="UTC hour from which a missing list counts as missing")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    ok, msg = verdict(logged_days(args.predictions), today, now.hour, args.after_hour)
    print(msg if ok else msg.splitlines()[0])
    if ok:
        return 0

    state = read_state(args.state)
    if state.get("last_alerted") == today:
        print("bugün için zaten uyarı gönderildi — tekrarlamıyor")
        return 0
    if args.dry_run:
        print("\n--- uyarı önizleme ---\n")
        print(msg)
        return 0

    sent, detail = telegram.send(msg)
    print(f"telegram: {'OK' if sent else 'gönderilemedi'} — {detail}")
    if sent:
        os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
        with open(args.state, "w") as f:
            json.dump({"last_alerted": today}, f)
    # A missing alarm must not fail the workflow on top of the thing it was reporting.
    return 0


if __name__ == "__main__":
    sys.exit(main())
