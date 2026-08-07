#!/usr/bin/env python3
"""Send today's combine to the existing Telegram channel: the PDF as an attachment, a
short Turkish caption on top of it — same shape the old product used for picks.html
(CLAUDE.md's Output section: "sent to Telegram as an attachment with a SHORT notice as
its caption"), reusing engine/telegram.py and the SAME TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID secrets rather than a second bot (docs/DECISIONS/0007).

    python tools/notify_combine.py --input combine.json --pdf combine_report.pdf

A SEPARATE step from tools/daily_combine.py on purpose: daily_combine.py cannot send the
PDF itself because combine_report.pdf does not exist yet when it finishes — rendering it
is tools/make_pdf_report.py's own job, run after. This script only reads what both of
those already wrote and sends it; it never recomputes anything.

A credential problem must never fail a run that otherwise worked: with no token configured
this exits 0 having sent nothing, exactly like engine/telegram.py's own no-op contract.
"""
import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import telegram  # noqa: E402


def build_caption(c):
    """The short Telegram message. The combine itself travels as the PDF attachment —
    a notification should say that today's analysis exists and how it looks, not carry
    the whole thing itself (same reasoning CLAUDE.md records for the old product's own
    notice, which is exactly why the list there moved off Telegram and onto a page)."""
    date = c.get("date") or ""
    legs = c.get("legs") or []
    lines = [f"<b>⚽🎾 Günlük kombine hazır</b>  <i>{html.escape(date)}</i>", ""]
    if not legs:
        why = c.get("why") or "Bugün 80 eşiğini geçen bir kombine çıkmadı."
        lines += [f"<i>{html.escape(why)}</i>", ""]
    else:
        odds = c.get("combined_odds")
        prob = c.get("combined_probability")
        conf = c.get("avg_confidence")
        lines.append(
            f"<b>{len(legs)} bacaklı kombine</b>"
            + (f" · toplam oran <b>{odds:.2f}</b>" if odds else "")
        )
        stats = []
        if conf is not None:
            stats.append(f"ortalama güven <b>{conf:.0f}/100</b>")
        if prob is not None:
            # Modelin kendi iddiası (her bacağın model_survival'inin çarpımı) — kitabın
            # oranlarından türetilmiş bir sayı DEĞİL. "Birleşik başarı tahmini" ifadesi
            # PDF/HTML sayfalarıyla aynı, tarafsız etiketleme (docs/COUPON_OPTIMIZATION.md).
            stats.append(f"modelin birleşik başarı tahmini %{prob * 100:.1f}")
        if stats:
            lines.append(" · ".join(stats))
        lines += [
            "",
            "📄 Tam gerekçe ekte (PDF) — her bacağın yönü, veri kalitesi ve hakem "
            "kurulu kararı dahil.",
            "",
        ]
        if c.get("coupon_code"):
            lines += [
                f"🎟 <b>Kupon kodu: <code>{html.escape(c['coupon_code'])}</code></b>",
                f"Betwinner'da <i>Kuponu yükle</i> kutusuna girin — "
                f"{html.escape(c.get('coupon_detail') or '')} tek seferde kupona düşer. "
                f"⚠️ <b>KOMBİNE olarak gelir</b>; gerekiyorsa kupon ekranından ayarlayın.",
                "",
            ]
    lines += ["<i>Yön modelden gelir, orandan değil. Puan analiz katmanından hesaplanır, "
              "kitabın fiyatı puana girmez. Bu bir garanti değildir.</i>"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="combine.json")
    ap.add_argument("--pdf", default="combine_report.pdf")
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"{args.input} yok — bildirilecek bir şey yok", file=sys.stderr)
        return 0

    with open(args.input) as f:
        c = json.load(f)

    caption = build_caption(c)
    if args.no_telegram:
        print("\n--- notice preview ---\n")
        print(caption)
        return 0

    if os.path.exists(args.pdf):
        ok, detail = telegram.send_document(args.pdf, caption=caption, parse_mode="HTML")
        if not ok and telegram.configured():
            # An upload can fail for reasons the text message will not — size, MIME, a
            # transient 5xx. The notice still has to arrive, so fall back to sending it
            # alone (same fallback the old product used for picks.html).
            print(f"telegram document: NOT SENT — {detail}", file=sys.stderr)
            ok, detail = telegram.send(caption)
    else:
        print(f"{args.pdf} yok — sadece metin gönderiliyor", file=sys.stderr)
        ok, detail = telegram.send(caption)
    print(f"telegram: {'OK' if ok else 'NOT SENT'} — {detail}")
    # A missing/broken credential must not fail a run that otherwise worked.
    return 0


if __name__ == "__main__":
    sys.exit(main())
