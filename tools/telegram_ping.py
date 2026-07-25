#!/usr/bin/env python3
"""Confirm the Telegram credentials work, before anything expensive runs.

    python tools/telegram_ping.py            # send a short confirmation
    python tools/telegram_ping.py --quiet    # check config only, send nothing

Exit codes are the point of this script:
    0  credentials absent (nothing to check) OR the send succeeded
    1  credentials ARE set but the send failed

That asymmetry is deliberate. A missing token is a valid state — the daily run still
scans and still writes its report, it just cannot notify. A token that is present and
broken is a real fault, and it should surface in the five seconds before the fetch rather
than two hours later when the report has nowhere to go.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import telegram  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="check configuration, send nothing")
    ap.add_argument("--text", default="")
    args = ap.parse_args()

    if not telegram.configured():
        print("Telegram: not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID absent).")
        print("The run will continue and the notification will be skipped.")
        return 0

    if args.quiet:
        print("Telegram: credentials present.")
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = args.text or (
        "<b>✅ Betwinner analiz botu bağlandı</b>\n"
        f"<i>{now}</i>\n\n"
        "Günlük rapor her gün 06:10 UTC (TR 09:10) bu sohbete gelecek:\n"
        "• önümüzdeki 24 ve 48 saat\n"
        "• minimum oran 1.10\n"
        "• yön modelden, en garanti bahis biçimi merdivenden\n"
        "• maç başına tek seçim, aynı gün sonuçlanan bahisler"
    )
    ok, detail = telegram.send(text)
    print(f"Telegram: {'OK' if ok else 'FAILED'} — {detail}")
    # Credentials are set, so a failure here is a real fault worth stopping for.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
