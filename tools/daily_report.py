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
from engine import (bwfeed, model_elo, model_football, parlay, pick, score,  # noqa: E402
                    settlement, telegram, tr)


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


def analyse(rows, hours, index, elo_model=None):
    """One window's worth of analysis."""
    windowed = within(rows, hours)
    multi_day = getattr(config, "MULTI_DAY_SPORTS", set())
    windowed = [r for r in windowed if r.get("sport_id") not in multi_day]
    matches = {r.get("match_id", r["fixture_id"]) for r in windowed}
    if not windowed:
        return {"hours": hours, "matches": 0, "picks": [], "skipped": {}}

    picks, skipped = pick.for_fixtures(rows=windowed, index=index, elo_model=elo_model)
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


def format_window(res):
    """Telegram HTML for one window."""
    h = res["hours"]
    lines = [f"<b>▸ Önümüzdeki {h} saat</b>"]
    if not res["matches"]:
        lines.append("  Bu pencerede maç yok.")
        return "\n".join(lines)

    sk = res.get("skipped") or {}
    lines.append(
        f"  {res['matches']} maç · {res.get('sports', 0)} spor · "
        f"<b>{len(res['picks'])} seçim</b>"
    )
    if not res["picks"]:
        lines.append("  <i>Güvenli eşiği geçen seçim çıkmadı.</i>")
    for p in res["picks"]:
        surv = p["model_survival"] * 100
        st = p.get("settlement") or {}
        warn = " ⚠" if st.get("needs_confirmation") else ""
        lines.append(
            f"\n  <b>{html.escape(p['p1'])} - {html.escape(p['p2'])}</b>"
            f"\n  <i>{html.escape(str(p.get('league') or ''))}</i> · "
            f"{html.escape((p.get('start') or '')[:16].replace('T', ' '))}"
            f"\n  ➤ {html.escape(tr.pick(p))} "
            f"<b>@{p['odds']:.2f}</b>"
            f"\n  model: %{surv:.1f} tutma · {html.escape(tr.scope(st.get('scope')))}{warn}"
        )
    lines.append(
        f"\n  <i>modelsiz {sk.get('no_model', 0)} maç · "
        f"eşiği geçemeyen {sk.get('no_confident_rung', 0)} maç</i>"
    )
    return "\n".join(lines)


def build_message(results, source_note=""):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = [
        f"<b>🎯 Betwinner günlük analiz</b>  <i>{now}</i>",
        f"min oran {config.MIN_ODDS:.2f} · model güven eşiği %{config.MIN_MODEL_SURVIVAL * 100:.0f} "
        f"· maç başına tek seçim",
        "",
    ]
    body = [format_window(r) for r in results]

    total = sum(len(r["picks"]) for r in results)
    tail = [""]
    if total:
        # Only legs with a measurable hold enter the combined figures — the alternative
        # is quietly inventing one, and hard rule 4's numbers are the whole point.
        legs = [p for p in results[-1]["picks"] if p.get("overround") is not None]
        s = parlay.summarize(legs)
        if s:
            tail += [
                "<b>▸ Kombine (48s seçimleri)</b>",
                f"  {s['legs']} bacak · oran <b>{s['combined_odds']:,.2f}</b>",
                f"  kitabın kendi olasılığı {s['combined_book_implied_prob']:.2e} "
                f"(~1/{s['one_in']:,.0f})",
                f"  beklenen getiri çarpanı {s['book_expected_return_multiple']:.4f} "
                f"— tek kitapta kombine <b>yapı gereği</b> pozitif beklenti taşımaz",
            ]
    else:
        tail += ["<i>Bugün için güvenli seçim üretilemedi.</i>"]

    tail += [
        "",
        "<i>Yön modelden gelir, orandan değil. Oran yalnızca 1.10 eşiğinde okunur. "
        "Uzun vadeli ve aynı gün sonuçlanmayan bahisler kapsam dışıdır.</i>",
    ]
    if source_note:
        tail += [f"<i>{html.escape(source_note)}</i>"]
    return "\n".join(head + body + tail)


def log_predictions(results, path):
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
    try:
        index = model_football.build_index()
        print(f"ClubElo fixtures indexed: {len(index)}")
    except Exception as e:
        print(f"ClubElo unavailable: {e}", file=sys.stderr)
        index = {}

    windows = [int(w) for w in args.windows.split(",") if w.strip()]
    results = [analyse(rows, h, index, elo_model) for h in windows]

    for r in results:
        print(f"  {r['hours']}h: {r['matches']} matches -> {len(r['picks'])} picks "
              f"(skipped: {r.get('skipped')})")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "min_odds": config.MIN_ODDS,
        "min_model_survival": config.MIN_MODEL_SURVIVAL,
        "windows": [
            {
                "hours": r["hours"],
                "matches": r["matches"],
                "skipped": r.get("skipped"),
                "picks": [
                    {
                        "match": f"{p['p1']} v {p['p2']}",
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
                        "url": parlay.betwinner_url(p),
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

    logged = log_predictions(results, args.predictions_log)
    print(f"prediction log: {logged} new rows in {args.predictions_log}")

    message = build_message(results, source_note=f"kaynak: {os.path.basename(args.input)}")
    if args.no_telegram:
        print("\n--- message preview ---\n")
        print(message)
        return 0

    ok, detail = telegram.send(message)
    print(f"telegram: {'OK' if ok else 'NOT SENT'} — {detail}")
    # A missing token must not fail a scan that otherwise worked.
    return 0


if __name__ == "__main__":
    sys.exit(main())
