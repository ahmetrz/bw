#!/usr/bin/env python3
"""The daily run: analyse the next 24 and 48 hours and report to Telegram.

    python tools/daily_report.py --input data/betwinner_48h.json.gz

Pipeline, in the order the operator's rules require:
    fetch window -> drop outrights and multi-day sports -> scan and score
    -> model gives each match a DIRECTION -> ladder converts it to its SAFEST form
    -> odds checked once, at the 1.10 gate -> confidence floor -> one pick per match

Everything settles the same day by construction: outrights carry no opponent and are
dropped at parse time, and the sports whose head-to-heads span days are excluded in
config.MULTI_DAY_SPORTS.

The report says how many matches the model could NOT reach. That number is the honest
headline of this product right now and it is not buried.
"""
import argparse
import gzip
import html
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import (bwfeed, mirror, model_elo, model_football, model_tt,  # noqa: E402
                    parlay, pick, rating, score, setka, settlement, telegram, tr)
from tools import make_picks_page  # noqa: E402


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def within(rows, hours, now=None):
    """Rows whose fixture starts inside the window. Starts already past are dropped —
    that is in-play territory and this is a pre-match product."""
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() + hours * 3600
    out = []
    for r in rows:
        start = r.get("start")
        if not start:
            continue
        try:
            ts = datetime.fromisoformat(start).timestamp()
        except ValueError:
            continue
        if now.timestamp() <= ts <= cutoff:
            out.append(r)
    return out


def analyse(rows, hours, index, elo_model=None, tt=None):
    """One window's worth of analysis."""
    windowed = within(rows, hours)
    multi_day = getattr(config, "MULTI_DAY_SPORTS", set())
    windowed = [r for r in windowed if r.get("sport_id") not in multi_day]
    matches = {r.get("match_id", r["fixture_id"]) for r in windowed}
    if not windowed:
        return {"hours": hours, "matches": 0, "picks": [], "skipped": {}}

    picks, skipped = pick.for_fixtures(rows=windowed, index=index, elo_model=elo_model, tt=tt)
    settlement.annotate(picks)
    # Picks come from the unfiltered rows, so they carry no hold yet. Attach it here so
    # the parlay's hard-rule-4 figures can be computed from the same numbers as the scan.
    over = score.overrounds(windowed)
    for p in picks:
        p["overround"] = over.get(p["market_key"])
    return {
        "hours": hours,
        "matches": len(matches),
        "sports": len({r.get("sport_id") for r in windowed}),
        "picks": picks,
        "skipped": skipped,
    }


def pick_key(p):
    """Identity of a selection, independent of which window produced it.

    The 24h card is a subset of the 48h card, but the two windows are analysed
    separately and so produce separate dicts for the same fixture. This is what lets a
    selection keep ONE number across both.
    """
    return (p.get("match_id", p.get("fixture_id")), p["market_key"][1], p.get("outcome_id"))


SCORE_FIELDS = ("id", "score", "confidence_points", "evidence_points",
                "confidence_pct", "evidence_pct")


def number(results):
    """Score every selection out of 100 and number them 1..N, best first.

    Numbered ONCE over the full card rather than per window, so #7 is the same bet
    whether you are looking at the 24h list or the 48h one. Numbering each window on its
    own would give two different bets the same number on the same page.
    """
    if not results:
        return results
    full = max(results, key=lambda r: r["hours"])
    rating.annotate(full["picks"])
    known = {pick_key(p): p for p in full["picks"]}
    for r in results:
        if r is full:
            continue
        for p in r["picks"]:
            src = known.get(pick_key(p))
            if src is None:
                # Cannot normally happen — a shorter window is a subset. Score it anyway
                # rather than emit a selection with no rating at all.
                p.update(rating.score(p))
                continue
            for k in SCORE_FIELDS:
                p[k] = src[k]
        r["picks"].sort(key=lambda p: p.get("id") or 10 ** 6)
    return results


def build_notice(results, page_name, host=None, host_source="", source_note=""):
    """The short Telegram message. The list itself travels as the attached page.

    Nine messages of selections could not be sorted, filtered or searched, and scrolling
    them on a phone was the worst way to read a ranked list. So this says only what a
    notification should: that today's analysis exists, how big it is and how good the
    top of it looks.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_hours = {r["hours"]: r for r in results}
    full = max(results, key=lambda r: r["hours"]) if results else None
    picks = full["picks"] if full else []

    lines = [f"<b>🎯 Betwinner günlük analiz hazır</b>  <i>{now}</i>", ""]
    if not picks:
        lines += ["<i>Bugün güvenli eşiği geçen seçim çıkmadı.</i>", ""]
    else:
        short = by_hours.get(24)
        lines += [
            f"<b>{len(picks)} seçim</b> · {full['hours']} saatlik kart"
            + (f" (24 saat içinde {len(short['picks'])})" if short else ""),
            f"en yüksek puan <b>{picks[0]['score']:.0f}/100</b> · "
            f"ortalama {sum(p['score'] for p in picks) / len(picks):.0f}",
            f"min oran {config.MIN_ODDS:.2f} · model güven eşiği "
            f"%{config.MIN_MODEL_SURVIVAL * 100:.0f} · maç başına tek seçim",
            "",
            f"📄 Liste ekteki <b>{html.escape(page_name)}</b> dosyasında: spora, pencereye, "
            "puana ve orana göre filtrelenebilir, sütun başlıklarından sıralanabilir, "
            "her satırda bahsin bağlantısı var.",
            "",
        ]
    lines += ["<i>Yön modelden gelir, orandan değil; oran yalnızca 1.10 eşiğinde okunur. "
              "Puan tamamen analizden hesaplanır, kitabın fiyatı puana girmez.</i>"]
    if host:
        lines += [f"<i>bağlantılar {html.escape(host)} üzerinden "
                  f"({html.escape(host_source)})</i>"]
    if source_note:
        lines += [f"<i>{html.escape(source_note)}</i>"]
    return "\n".join(lines)


def log_predictions(results, path, host=None):
    """Append every selection to the permanent prediction log, for later grading.

    Written the moment the pick is made, never reconstructed afterwards. A record built
    after the fact could quietly be a record of what we WOULD have picked, which is how a
    backtest flatters itself; this is what was actually offered, at the odds actually
    available, before the result was known.

    Deduplicated on (date, match, market, selection) so re-running a day is harmless.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seen.add((r.get("date"), r.get("match_id"), r.get("market_line"),
                          r.get("outcome_id")))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = datetime.now(timezone.utc).isoformat()
    added = 0
    # The longest window is the full card; shorter windows are subsets of it, so logging
    # only the last window records each pick once.
    for p in (results[-1]["picks"] if results else []):
        key = (today, p.get("match_id", p.get("fixture_id")),
               p["market_key"][1], p.get("outcome_id"))
        if key in seen:
            continue
        with open(path, "a") as f:
            f.write(json.dumps({
                "date": today,
                "logged_at": stamp,
                "id": p.get("id"),
                "score": p.get("score"),
                "confidence_pct": p.get("confidence_pct"),
                "evidence_pct": p.get("evidence_pct"),
                "match_id": p.get("match_id", p.get("fixture_id")),
                "sport_id": p.get("sport_id"),
                "division": (p.get("model_probs") or {}).get("_division")
                            or p.get("division"),
                "league": p.get("league"),
                "start": p.get("start"),
                "p1": p.get("p1"), "p2": p.get("p2"),
                "market_line": p["market_key"][1],
                "outcome_id": p.get("outcome_id"),
                "selection": p.get("selection"),
                "selection_tr": tr.pick(p),
                "ladder_rung": p.get("ladder_rung"),
                "direction": p.get("direction"),
                "odds": p.get("odds"),
                "model_survival": p.get("model_survival"),
                "model_source": p.get("model_source"),
                "url": parlay.betwinner_url(p, host),
                "result": None,
            }, ensure_ascii=False) + "\n")
        seen.add(key)
        added += 1
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--predictions-log", default="data/predictions.jsonl")
    ap.add_argument("--windows", default=",".join(str(h) for h in config.DAILY_WINDOWS_HOURS))
    ap.add_argument("--out", default="daily_report.json")
    ap.add_argument("--page", default="picks.html")
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()

    data = load(args.input)
    if not bwfeed.is_bwfeed(data):
        print("Input is not a Betwinner feed pull — refusing to proceed.", file=sys.stderr)
        return 1

    rows = bwfeed.normalize(data)
    print(f"normalized rows: {len(rows)} from {len(data)} feed entries")

    # Our own model first — it is fitted from history and works out of season.
    elo_model = model_elo.load()
    if elo_model:
        print(f"Elo model: {len(elo_model['divisions'])} divisions, "
              f"{elo_model['matches']} matches fitted")
    else:
        print("Elo model absent — run tools/build_football_model.py", file=sys.stderr)
    # Table tennis: the calibrated Setka model plus the live rating index.
    tt = None
    tt_model = model_tt.load()
    if tt_model:
        try:
            tt = (tt_model, model_tt.build_player_index(setka.ratings()))
            print(f"Table tennis model: {tt_model['samples']} samples, "
                  f"logloss {tt_model['logloss']} vs {tt_model['baseline_logloss']} baseline; "
                  f"{len(tt[1].get('exact', {}))} rated players")
        except Exception as e:
            print(f"Setka ratings unavailable: {e}", file=sys.stderr)
    else:
        print("Table tennis model absent — run tools/build_tt_model.py", file=sys.stderr)

    try:
        index = model_football.build_index()
        print(f"ClubElo fixtures indexed: {len(index)}")
    except Exception as e:
        print(f"ClubElo unavailable: {e}", file=sys.stderr)
        index = {}

    windows = [int(w) for w in args.windows.split(",") if w.strip()]
    results = number([analyse(rows, h, index, elo_model, tt) for h in windows])

    for r in results:
        print(f"  {r['hours']}h: {r['matches']} matches -> {len(r['picks'])} picks "
              f"(skipped: {r.get('skipped')})")

    host, host_source = mirror.current(getattr(config, "REFERRAL_URL", None))
    print(f"link host: {host} ({host_source})")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "link_host": host,
        "min_odds": config.MIN_ODDS,
        "min_model_survival": config.MIN_MODEL_SURVIVAL,
        "windows": [
            {
                "hours": r["hours"],
                "matches": r["matches"],
                "skipped": r.get("skipped"),
                "picks": [
                    {
                        "id": p.get("id"),
                        "score": p.get("score"),
                        "confidence_pct": p.get("confidence_pct"),
                        "evidence_pct": p.get("evidence_pct"),
                        "match": f"{p['p1']} v {p['p2']}",
                        "p1": p.get("p1"), "p2": p.get("p2"),
                        "league": p.get("league"),
                        "start": p.get("start"),
                        "sport_id": p.get("sport_id"),
                        "selection": p["selection"],
                        "selection_tr": tr.pick(p),
                        "ladder_rung": p.get("ladder_rung"),
                        "direction": p.get("direction"),
                        "odds": p["odds"],
                        "model_survival": p["model_survival"],
                        "settlement": p.get("settlement"),
                        "url": parlay.betwinner_url(p, host),
                    }
                    for p in r["picks"]
                ],
            }
            for r in results
        ],
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}")

    n = make_picks_page.build(payload, args.page)
    print(f"wrote {args.page} — {n} selections")

    logged = log_predictions(results, args.predictions_log, host)
    print(f"prediction log: {logged} new rows in {args.predictions_log}")

    notice = build_notice(results, os.path.basename(args.page), host=host,
                          host_source=host_source,
                          source_note=f"kaynak: {os.path.basename(args.input)}")
    if args.no_telegram:
        print("\n--- notice preview ---\n")
        print(notice)
        return 0

    # The page goes as the attachment and the notice as its caption, so the whole daily
    # report arrives as ONE Telegram item instead of nine walls of text.
    ok, detail = telegram.send_document(args.page, caption=notice, parse_mode="HTML")
    if not ok and telegram.configured():
        # An upload can fail for reasons the text message will not — size, MIME, a
        # transient 5xx. The notice still has to arrive, so fall back to sending it alone.
        print(f"telegram document: NOT SENT — {detail}", file=sys.stderr)
        ok, detail = telegram.send(notice)
    print(f"telegram: {'OK' if ok else 'NOT SENT'} — {detail}")
    # A missing token must not fail a scan that otherwise worked.
    return 0


if __name__ == "__main__":
    sys.exit(main())
