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
from engine import (bwfeed, coupon, mirror, model_elo, model_football,  # noqa: E402
                    model_generic, model_tt, parlay, pick, rating, results_store,
                    score, setka, settlement, simulated, stake, telegram, tr)
from tools import collect_live, fetch_window, make_picks_page  # noqa: E402


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


def analyse(rows, hours, index, elo_model=None, tt=None, generic=None, fake=None):
    """One window's worth of analysis."""
    windowed = within(rows, hours)
    multi_day = getattr(config, "MULTI_DAY_SPORTS", set())
    windowed = [r for r in windowed if r.get("sport_id") not in multi_day]
    if fake:
        windowed = [r for r in windowed
                    if (r.get("sport_id"), r.get("league")) not in fake]
    matches = {r.get("match_id", r["fixture_id"]) for r in windowed}
    if not windowed:
        return {"hours": hours, "matches": 0, "picks": [], "skipped": {}}

    picks, skipped = pick.for_fixtures(rows=windowed, index=index, elo_model=elo_model,
                                       tt=tt, generic=generic)
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


def skipped_at_fetch(card_path):
    """What the fetcher left on the card without pulling, and why.

    The fetcher now applies two rules — excluded sports, and hard rule 7's "no second
    participant is not a head-to-head" — at ENUMERATION rather than after pulling a
    thousand events for each fixture. That is a large saving and it would otherwise make
    those sports disappear from this report entirely, which is the exact failure this
    report exists to prevent. So the fetcher writes down what it skipped and the count is
    read back here.
    """
    if not card_path:
        return {}
    try:
        with open(fetch_window.skipped_path(card_path)) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for reason, per_sport in (data or {}).items():
        for sid, n in (per_sport or {}).items():
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                continue
            got = out.setdefault(sid, {"matches": 0, "reason": reason})
            got["matches"] += int(n or 0)
    return out


def _eta(sid, have, _ledger=[]):
    """" — canlı izleyici günde ~N topluyor, bu hızla ~M gün", when that can be measured.

    The operator's standing question about this product has been "when do the other sports
    show up", and the honest answer changes every day as the watcher runs. So it is
    computed rather than asserted.

    From the LEDGER rather than from the store, because the store cannot answer it. It
    keeps each fixture's own date, not the moment we learned of it, so a watcher three
    hours old and one a day old look identical — the first version of this read the store
    and told the operator volleyball was 28 days away when the measured rate put it at
    three. The ledger records what was collected and when, so the rate is per HOUR of
    actual watching and the projection follows from it.
    """
    if not _ledger:
        _ledger.append(_read_ledger())
    rows = [r for r in _ledger[0] if r.get("sport") == sid]
    if len(rows) < 2:
        return " — canlı izleyici biriktiriyor"
    stamps = sorted(r["at"] for r in rows)
    try:
        span = ((datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
                 - datetime.fromisoformat(stamps[0].replace("Z", "+00:00")))
                .total_seconds() / 3600.0)
    except ValueError:
        return " — canlı izleyici biriktiriyor"
    if span < 1.0:
        return " — canlı izleyici biriktiriyor"
    # n entries are n runs, but the span between the first and the last covers only n-1
    # gaps. Dividing by the raw span would credit every run's yield to one fewer run's
    # worth of watching, which overstates the rate by half when there are only two points.
    watched = span * len(rows) / (len(rows) - 1)
    per_day = sum(r.get("added", 0) for r in rows) / watched * 24.0
    if per_day <= 0:
        return " — canlı izleyici biriktiriyor"
    left = (model_generic.MIN_RESULTS - have) / per_day
    if left <= 1:
        return " — canlı izleyici biriktiriyor, bugün yarın dolar"
    return (f" — canlı izleyici günde ~{per_day:.0f} topluyor, "
            f"bu hızla ~{left:.0f} gün")


def _read_ledger(path=None):
    path = path or collect_live.LEDGER
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return out


def _why_no_model(sid, _cache={}):
    """Why this sport produced nothing, in the words that say what happens next.

    "No results data — no adapter written" was true when every sport needed somebody
    else's archive. It stopped being true the day the live watcher went in: fencing,
    volleyball and esports are not waiting for an adapter, they are waiting for matches to
    finish. Those are different situations and only one of them is work for a person.
    """
    if not _cache:
        _cache.update(results_store.summary() or {"_": None})
    stored = _cache.get(sid)
    if stored:
        # A model file exists for every sport with any results at all, so "refused" is the
        # wrong word while a sport is simply still filling. `usable` answers "no
        # calibration table" for a model built from six results, which is true and tells
        # the operator nothing about whether anything is wrong or how far off it is.
        if stored["games"] < model_generic.MIN_RESULTS:
            return (f"{stored['games']} sonuç toplandı, kalibrasyon için "
                    f"{model_generic.MIN_RESULTS} gerekiyor{_eta(sid, stored['games'])}")
        model = model_generic.load(sid)
        if model:
            return f"model reddedildi: {model_generic.usable(model)[1]}"
        return f"{stored['games']} sonuç toplandı, model henüz kurulmadı"
    if sid in collect_live.SPORTS:
        return "canlı izleniyor — sonuçlar biriktikçe modellenecek"
    why = collect_live.UNWATCHABLE.get(sid)
    return f"modellenemez: {why}" if why else "sonuç kaynağı yok"


def coverage(rows, results, generic, card_path=None):
    """Per sport: what was on the card, what was priced, and WHY the rest was not.

    This exists because the operator kept discovering the same class of problem by
    accident — "only football and table tennis" was true for weeks and nothing said so
    where it would be read. A gap that is reported every day is a decision; a gap you
    trip over is a surprise, and surprises are what made this expensive.
    """
    full = max(results, key=lambda r: r["hours"]) if results else None
    if not full:
        return []
    by_sport = {}
    for r in rows:
        sid = r.get("sport_id")
        by_sport.setdefault(sid, set()).add(r.get("match_id", r["fixture_id"]))
    # Sports the fetcher never pulled still belong in the report, with their real count.
    never_fetched = skipped_at_fetch(card_path)
    picked = {}
    for p in full["picks"]:
        sid = p.get("sport_id")
        picked[sid] = picked.get(sid, 0) + 1
    # Where the matches we DID look at went. On a real card this is the whole story: of
    # 1,227 head-to-head fixtures, 858 were in sports we model and were dropped because
    # the model does not know the two participants. That is not a filter to loosen, it is
    # history we do not have yet, and it belongs in the report per sport.
    unknown = (full.get("skipped") or {}).get("no_model_by_sport") or {}
    no_rung = (full.get("skipped") or {}).get("no_rung_by_sport") or {}

    excluded = getattr(config, "EXCLUDED_SPORTS", set())
    multi_day = getattr(config, "MULTI_DAY_SPORTS", set())
    out = []
    for sid, matches in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        if sid in excluded:
            state, detail = "excluded", "config.EXCLUDED_SPORTS"
        elif sid in multi_day:
            state, detail = "excluded", "aynı gün sonuçlanmıyor"
        elif sid in pick.MODELLED_SPORTS:
            state, detail = "modelled", "hand-written model"
        elif sid in (generic or {}):
            model = generic[sid]
            worst = max(abs(c["predicted"] - c["observed"])
                        for c in model["calibration"])
            state = "modelled"
            detail = f"generic, {model['games']} sonuç, kalibrasyon {worst:.3f}"
        else:
            state, detail = "no_model", _why_no_model(sid)
        out.append({
            "sport_id": sid,
            "sport": tr.sport(sid, str(sid)),
            "matches": len(matches),
            "picks": picked.get(sid, 0),
            # Of this sport's matches: how many the model could not identify the teams
            # for, and how many it priced but found no rung above the gates.
            "unknown_teams": unknown.get(sid, 0),
            "no_rung": no_rung.get(sid, 0),
            "state": state,
            "detail": detail,
        })
    for sid, info in never_fetched.items():
        if sid in by_sport:
            continue
        out.append({
            "sport_id": sid,
            "sport": tr.sport(sid, str(sid)),
            "matches": info["matches"],
            "picks": 0,
            "state": "excluded",
            "detail": ("config.EXCLUDED_SPORTS — kart çekilirken atlandı"
                       if info["reason"] == "excluded_sport"
                       else "ikinci taraf yok, ikili karşılaşma değil — çekilirken atlandı"),
        })
    out.sort(key=lambda r: -r["matches"])
    return out


def pick_key(p):
    """Identity of a selection, independent of which window produced it.

    The 24h card is a subset of the 48h card, but the two windows are analysed
    separately and so produce separate dicts for the same fixture. This is what lets a
    selection keep ONE number across both.
    """
    return (p.get("match_id", p.get("fixture_id")), p["market_key"][1], p.get("outcome_id"))


SCORE_FIELDS = ("id", "score", "band", "model_pct", "evidence_pct", "evidence_penalty")


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


def apply_stakes(results):
    """Size every selection and return the day's staking summary.

    Sized once, on the widest window, and copied to the others by id — for the same
    reason the numbering is: the 24h list is a subset of the 48h one, and a selection
    that is #7 with one unit on it must not become #7 with nothing on it because a
    shorter window happened to contain fewer selections above it.
    """
    if not results:
        return None
    full = max(results, key=lambda r: r["hours"])
    summary = stake.plan(full["picks"])
    sized = {p.get("id"): (p["stake"], p["in_plan"]) for p in full["picks"]}
    for r in results:
        if r is full:
            continue
        for p in r["picks"]:
            p["stake"], p["in_plan"] = sized.get(p.get("id"), (0.0, False))
    return summary


def build_notice(results, page_name, host=None, host_source="", source_note="",
                 coupon_code=None, coupon_detail="", staking=None):
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
            f"en iyi seçim <b>{picks[0]['score']:.0f}/100</b> "
            f"({html.escape(str(picks[0].get('band') or ''))}) · "
            f"ortalama {sum(p['score'] for p in picks) / len(picks):.0f} · "
            f"puan = modelin tutma olasılığı",
            f"min oran {config.MIN_ODDS:.2f} · model güven eşiği "
            f"%{config.MIN_MODEL_SURVIVAL * 100:.0f} · maç başına tek seçim",
            "",
            f"📄 Liste ekte: <b>{html.escape(page_name)}</b> — filtrelenir, sıralanır, "
            "her satırda bahsin bağlantısı var.",
            "",
        ]
        if staking and staking.get("placed"):
            # What the day COSTS, which the list on its own does not say. ONE line: the
            # caption is capped at 1024 characters and clipped on a line boundary, so
            # every line added here is a line that can push the coupon code off the end.
            # The reasoning — why the stakes are equal, what break-even means — is on the
            # page, which is where it can be read properly anyway.
            lines += [
                f"💰 <b>{staking['placed']} bahis × %{staking['unit_pct']:g} kasa</b> = "
                f"ortaya konan <b>%{staking['risk_pct']:g}</b> · başabaş isabet "
                f"<b>%{(staking.get('break_even_rate') or 0) * 100:.1f}</b>"
                + (f" · tavan dışı {staking['left_out']}"
                   if staking.get("left_out") else "")
                + (" · <i>birim/tavan onayınızı bekliyor</i>"
                   if staking.get("provisional") else ""),
                "",
            ]
        if coupon_code:
            lines += [
                f"🎟 <b>Kupon kodu: <code>{html.escape(coupon_code)}</code></b>",
                f"Betwinner'da <i>Kuponu yükle</i> kutusuna bu kodu girin — "
                f"{html.escape(coupon_detail)} tek seferde kupona düşer, her biri "
                f"AYRI bahis olarak. Kombine değil: plan her seçime aynı miktarı "
                f"koymak, biri kaybederse diğerlerinin ayakta kalması üzerine kurulu.",
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


def logged_today(path, day=None):
    """Has a list already been recorded for today? The permanent log is the only witness.

    Deliberately not "did a file get written" — picks.html and daily_report.json are
    rebuilt by anything that runs, while a prediction row is written once and never
    reconstructed. It is the one artefact that answers "was the operator given a list".
    """
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("date") == day:
                    return True
            except json.JSONDecodeError:
                continue
    return False


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
                "band": p.get("band"),
                "model_pct": p.get("model_pct"),
                "evidence_pct": p.get("evidence_pct"),
                "match_id": p.get("match_id", p.get("fixture_id")),
                "sport_id": p.get("sport_id"),
                "division": (p.get("model_probs") or {}).get("_division")
                            or p.get("division"),
                "league": p.get("league"),
                "start": p.get("start"),
                "p1": p.get("p1"), "p2": p.get("p2"),
                # The book's own participant ids. Written here so the GRADER can match
                # this fixture to a result exactly, instead of normalizing two names and
                # hoping. The live watcher records results under the same ids.
                "p1_id": p.get("p1_id"), "p2_id": p.get("p2_id"),
                "market_line": p["market_key"][1],
                # Which SECTION of the fixture page this bet lives in. Written here so the
                # evening scorecard can show it too — it is rebuilt from this log, not from
                # the morning report, and without it the operator sees the selection but
                # not where to find it.
                "market_type": p.get("market_type"),
                "outcome_id": p.get("outcome_id"),
                "selection": p.get("selection"),
                "selection_tr": tr.pick(p),
                "ladder_rung": p.get("ladder_rung"),
                "direction": p.get("direction"),
                "odds": p.get("odds"),
                "game_id": p.get("game_id"),
                # What was actually going to be RISKED on this selection. Recorded with
                # the pick, because the evening scorecard measures the day the operator
                # was handed and that day had a cap on it: an ROI computed over
                # thirty-four legs describes a bet nobody placed if the plan was twenty.
                "stake": p.get("stake"),
                "in_plan": p.get("in_plan"),
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
    ap.add_argument("--simulated-out", default=simulated.STORE)
    ap.add_argument("--no-coupon", action="store_true",
                    help="do not ask the book for a bet-slip code")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--only-if-new", action="store_true",
                    help="skip the Telegram send when every selection was already logged "
                         "(for backstop runs behind a schedule that may have fired)")
    args = ap.parse_args()

    # ONE LIST A DAY, AND THE BACKSTOPS MUST NOT REWRITE IT. The morning has three
    # scheduled attempts because GitHub drops fires — 06:10 once never ran at all — but
    # only the first of them is meant to produce anything. Checked HERE rather than at the
    # send, because a later run that rebuilt the page would hand the operator a different
    # list from the one they were notified about: fresh prices, a new bet-slip code, and
    # fixtures that have since dropped inside the 24-hour window.
    if args.only_if_new and logged_today(args.predictions_log):
        print("bugünün listesi zaten üretilmiş — yedek koşu hiçbir şeyi yeniden yazmıyor")
        return 0

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

    # Every generic model that PASSES its own held-out calibration. One line, and it is
    # the same line however many sports there eventually are.
    generic = {}
    for sid in sorted(results_store.summary()):
        model = model_generic.load(sid)
        ok, why = model_generic.usable(model)
        label = tr.sport(sid, str(sid))
        print(f"generic model {label} ({sid}): {'ADMITTED' if ok else 'refused'} — {why}")
        if ok:
            generic[sid] = model

    try:
        index = model_football.build_index()
        print(f"ClubElo fixtures indexed: {len(index)}")
    except Exception as e:
        print(f"ClubElo unavailable: {e}", file=sys.stderr)
        index = {}

    # Competitions whose schedule is physically impossible — a participant starting a
    # second fixture before the first could have ended. See engine/simulated.py. Written
    # out so the live watcher refuses to store their "results" too: the daily run sees the
    # whole 48-hour card, which is where the pattern is visible at all.
    fake = simulated.leagues(rows)
    for (sid, league), why in sorted(fake.items(), key=lambda kv: str(kv[0])):
        print(f"simulated: {tr.sport(sid, str(sid))} / {league} — {why}")
    simulated.save(fake, args.simulated_out)

    windows = [int(w) for w in args.windows.split(",") if w.strip()]
    results = number([analyse(rows, h, index, elo_model, tt, generic, fake)
                      for h in windows])
    staking = apply_stakes(results)
    if staking:
        print(f"\nstaking: {staking['placed']} × 1 birim (%{staking['unit_pct']}) = "
              f"kasanın %{staking['risk_pct']}'i risk altında · "
              f"{staking['left_out']} seçim tavanın dışında · "
              f"başabaş isabet %{(staking['break_even_rate'] or 0) * 100:.1f}"
              + ("  [ONAY BEKLİYOR — birim ve tavan operatörün]"
                 if staking["provisional"] else ""))

    for r in results:
        # The per-league breakdown lives in the coverage section below; dumping the whole
        # dict here buried the run's own log under a hundred competition names.
        sk = r.get("skipped") or {}
        print(f"  {r['hours']}h: {r['matches']} matches -> {len(r['picks'])} picks "
              f"(taraflar tanınmadı {sk.get('no_model', 0)} · "
              f"eşik geçmedi {sk.get('no_confident_rung', 0)} · "
              f"modelsiz spor {sk.get('unmodelled_sport', 0)})")

    host, host_source = mirror.current(getattr(config, "REFERRAL_URL", None))
    print(f"link host: {host} ({host_source})")

    cov = coverage(rows, results, generic, card_path=args.input)
    reach = sum(c["matches"] for c in cov if c["state"] == "modelled")
    total = sum(c["matches"] for c in cov)
    print(f"\ncoverage: {len(cov)} sports on the card, "
          f"{sum(1 for c in cov if c['state'] == 'modelled')} modelled, "
          f"{reach}/{total} matches reachable")
    for c in cov[:14]:
        # "tanınmadı" is the number that matters on a modelled sport: every one of those
        # matches WAS examined and was dropped because our history does not contain the
        # two participants. Loosening a gate would not recover a single one of them.
        gap = (f" · {c['unknown_teams']} tanınmadı" if c.get("unknown_teams") else "")
        gap += (f" · {c['no_rung']} eşik geçmedi" if c.get("no_rung") else "")
        print(f"  {c['sport'][:22]:<22} {c['matches']:>5} maç  {c['picks']:>4} seçim  "
              f"{c['state']:<10} {c['detail']}{gap}")
    checked = sum(c["matches"] for c in cov if c["state"] == "modelled")
    unknown_total = sum(c.get("unknown_teams", 0) for c in cov)
    norung_total = sum(c.get("no_rung", 0) for c in cov)
    picks_total = sum(c["picks"] for c in cov)
    print(f"\n  modellenen sporlarda {checked} maç incelendi: "
          f"{unknown_total} taraflar tanınmadı · {norung_total} eşikleri geçemedi · "
          f"{picks_total} seçim")
    widest = max(results, key=lambda r: r["hours"]) if results else {}
    leagues = (widest.get("skipped") or {}).get("no_model_leagues") or {}
    if leagues:
        print("  en çok tanınmayan müsabakalar (geçmişimizde yoklar):")
        for key, n in sorted(leagues.items(), key=lambda kv: -kv[1])[:8]:
            sid, _, name = key.partition("|")
            print(f"    {n:>4}  {tr.sport(int(sid), sid)} — {name}")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "coverage": cov,
        "link_host": host,
        "min_odds": config.MIN_ODDS,
        "min_model_survival": config.MIN_MODEL_SURVIVAL,
        "staking": staking,
        "windows": [
            {
                "hours": r["hours"],
                "matches": r["matches"],
                "skipped": r.get("skipped"),
                "picks": [
                    {
                        "id": p.get("id"),
                        "score": p.get("score"),
                        "band": p.get("band"),
                        "model_pct": p.get("model_pct"),
                        "evidence_pct": p.get("evidence_pct"),
                        "evidence_penalty": p.get("evidence_penalty"),
                        "match": f"{p['p1']} v {p['p2']}",
                        "p1": p.get("p1"), "p2": p.get("p2"),
                        "league": p.get("league"),
                        "start": p.get("start"),
                        "sport_id": p.get("sport_id"),
                        "selection": p["selection"],
                        "selection_tr": tr.pick(p),
                        # The section of the fixture page this bet lives in. Finding
                        # "Set Handikapı" among a hundred markets was always the slow
                        # part of adding a leg; the tap never was.
                        "market_type": p.get("market_type"),
                        "ladder_rung": p.get("ladder_rung"),
                        "direction": p.get("direction"),
                        "odds": p["odds"],
                        "stake": p.get("stake"),
                        "in_plan": p.get("in_plan"),
                        # The BETSLIP id, which is not the deep-link id. Written into the
                        # report because the bet-slip code has to be rebuilt hourly from
                        # fixtures that have not started yet, long after this run is over.
                        "game_id": p.get("game_id"),
                        "market_key": list(p["market_key"]),
                        "outcome_id": p.get("outcome_id"),
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

    # ONE CODE FOR THE DAY'S PLAN. The book's own share-a-slip endpoint takes a set of
    # events and returns a five-character code; typing it into "load bet slip" drops every
    # selection in at once. See engine/coupon.py for how it is verified before it is handed
    # over — a slip that loads the wrong bet in one tap is worse than no slip.
    #
    # It carries the selections INSIDE the day's cap and not the whole list. A code that
    # loaded thirty-four legs against a twenty-leg plan would leave fourteen to delete by
    # hand, which is the work this code exists to remove.
    coupon_code, coupon_detail = (None, "")
    if not args.no_coupon:
        widest_picks = (max(results, key=lambda r: r["hours"])["picks"] if results else [])
        widest_picks = [p for p in widest_picks if p.get("in_plan", True)]
        coupon_code, coupon_detail = coupon.create(widest_picks)
        print(f"kupon kodu: {coupon_code or '—'} ({coupon_detail})")
    payload["coupon_code"] = coupon_code
    payload["coupon_detail"] = coupon_detail

    n = make_picks_page.build(payload, args.page)
    print(f"wrote {args.page} — {n} selections")

    logged = log_predictions(results, args.predictions_log, host)
    print(f"prediction log: {logged} new rows in {args.predictions_log}")

    notice = build_notice(results, os.path.basename(args.page), host=host,
                          host_source=host_source,
                          source_note=f"kaynak: {os.path.basename(args.input)}",
                          coupon_code=coupon_code, coupon_detail=coupon_detail,
                          staking=staking)
    if args.no_telegram:
        print("\n--- notice preview ---\n")
        print(notice)
        return 0

    # A BACKSTOP RUN MUST NOT SEND THE SAME LIST TWICE. GitHub drops scheduled fires
    # often enough that the daily run needs more than one attempt in the morning — today's
    # 06:10 never fired at all, and without a manual trigger no list would have gone out.
    # More than one cron then risks two notifications for one card, so the later ones pass
    # --only-if-new: if every selection was already in the prediction log, the earlier run
    # succeeded and this one has nothing to announce.
    if args.only_if_new and not logged:
        print("bu kartın tüm seçimleri zaten kayıtlı — daha önceki koşu gönderdi, "
              "yedek koşu göndermiyor")
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
