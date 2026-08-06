#!/usr/bin/env python3
"""Fit the ONE model for a sport from data/results/<sport>.jsonl.

    python tools/build_generic_model.py --sport 3
    python tools/build_generic_model.py --all

There is no sport-specific code in here and there is not meant to be. Adding a sport to
this product is now: collect its results into the store, run this, read the calibration.
If the calibration holds, the sport is admitted; if it does not, it is refused and the
refusal says why. That is the whole loop, and it is the same loop for every sport.

The calibration is not decoration. It is computed by asking the model to price the very
lines the safety ladder selects, then counting how often those lines actually landed in
the same history. A model that disagrees with its own record is not wired in at all.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import governance, model_generic as mg, results_store, tr  # noqa: E402

# The plus-lines a safety ladder actually walks, per unit of scoring. A football ladder
# lives at +0.5 to +2.5; a basketball one at +6.5 to +20.5. Calibrating a football model
# at +12.5 goals would report a meaningless 100%.
LADDER_LINES = {
    "low": (0.5, 1.5, 2.5, 3.5),                   # goals, sets — football, hockey, TT
    "high": (2.5, 6.5, 10.5, 14.5, 20.5),          # points — basketball, handball
}


def scale_of(rows):
    """Which line scale this sport lives on, read off its own scores rather than a list."""
    if not rows:
        return "low"
    avg = sum(abs(r["home_score"] - r["away_score"]) for r in rows) / len(rows)
    return "high" if avg > 5.0 else "low"


def _appearances(rows):
    seen = {}
    for r in rows:
        for side in ("home", "away"):
            k = (mg.pool_of(r), mg.team_key(r, side))
            seen[k] = seen.get(k, 0) + 1
    return seen


def calibrate(rows, gaps, fit, bands, lines, seen=None):
    """Predicted cover rate against observed, on the lines the ladder selects.

    HELD OUT, and that word is the whole point. The first version counted the predictions
    and the outcomes from the same matches, so it reported a gap of 0.000 on every line —
    an arithmetic identity dressed up as a test. A check that cannot fail checks nothing,
    and this project already shipped one model whose confident wrongness only a real check
    would have caught. So the distributions come from the earlier matches and the
    comparison is made on the later ones the model has never seen.
    """
    # `bands` is now {pool: [band, ...]} with "" as the sport-wide fallback.
    fitted = {"line": fit, "bands": bands,
              "_margin": {k: [mg._pmf(b["margin"]) for b in v] for k, v in bands.items()}}
    out = []
    rows = sorted(rows, key=lambda x: x["date"])
    for line in lines:
        pred, hit, n = 0.0, 0, 0
        for r, eff in zip(rows, gaps):
            pool = mg.pool_of(r)
            # Calibrate on the fixtures the model would ACTUALLY price. Including matches
            # it refuses would measure a model nobody runs.
            if seen is not None and min(
                    seen.get((pool, mg.team_key(r, "home")), 0),
                    seen.get((pool, mg.team_key(r, "away")), 0)) < mg.MIN_APPEARANCES:
                continue
            pmf, mu, _ = mg.margin_pmf(fitted, eff, pool)
            # The UNDERDOG taking the points — the rung a safety ladder actually offers.
            dog = {-m: p for m, p in pmf.items()} if mu >= 0 else pmf
            pred += sum(p for m, p in dog.items() if m + line > 0)
            margin = r["home_score"] - r["away_score"]
            dog_margin = margin if mu < 0 else -margin
            hit += 1 if dog_margin + line > 0 else 0
            n += 1
        if not n:
            continue
        out.append({"line": line, "predicted": round(pred / n, 4),
                    "observed": round(hit / n, 4), "n": n})
    return out


def _by_pool(rating, latest):
    """pool -> {current team name: rating}. Names, because the book prints names."""
    out = {}
    for (pool, key), value in rating.items():
        out.setdefault(pool, {})[latest.get((pool, key), key)] = round(value, 1)
    return out


def _aliases_by_pool(aliases, latest):
    out = {}
    for (pool, key), names in aliases.items():
        current = latest.get((pool, key), key)
        for name in names:
            if name != current:
                out.setdefault(pool, {})[name] = current
    return out


def _book_ids(rows, latest):
    """pool -> {betwinner participant id: current team name}.

    Only from rows the live watcher collected, because only those ids came from the book.
    A source's own id — EuroLeague's club code, Setka's player id — identifies the team
    inside THAT source and means nothing on Betwinner's card, so mixing the two would
    resolve a fixture to whichever unrelated team happened to share a number.
    """
    out = {}
    for r in rows:
        if r.get("source") != "betwinner-live":
            continue
        pool = mg.pool_of(r)
        for side in ("home", "away"):
            bid = r.get(f"{side}_id")
            if not bid:
                continue
            key = (pool, mg.team_key(r, side))
            out.setdefault(pool, {})[str(bid)] = latest.get(key, r[side])
    return out


def _appearances_by_pool(seen, latest):
    out = {}
    for (pool, key), n in seen.items():
        out.setdefault(pool, {})[latest.get((pool, key), key)] = n
    return out


def _holdout_cut(rows):
    """Where to split TRAIN from TEST — the most recent ~20% of the DATE RANGE, not the
    most recent 20% of ROWS. `rows` must already be sorted by date.

    Approved structural change, `pmc-2026-08-06-tennis-split`
    (data/proposed_changes.jsonl, reviewed and approved by the operator): row-count-
    proportional splitting silently assumes roughly uniform row density over time, which
    held for football/basketball/baseball/table-tennis but broke for tennis specifically
    — TML's archive contributes ~2,700 rows/year over 11 years while tennisexplorer + the
    live watcher contributed thousands in the final weeks alone, so the "last 20% of
    rows" was the last 11 DAYS, dominated by a population (Challenger/ITF qualifiers) the
    training window barely covered. A date-proportional cut keeps the same chronological-
    only guarantee (hard rule 8 / fit_ratings' point-in-time discipline is untouched —
    this only decides WHERE to slice, never reorders anything) while staying robust to a
    density spike in any one sport. Full evidence: docs/TENNIS_MODELS.md.

    Falls back to the row-count method when the whole history spans under a day (dates
    cannot be usefully proportioned) or is unparseable — never raises.
    """
    from datetime import date, timedelta
    try:
        d0 = date.fromisoformat(rows[0]["date"][:10])
        d1 = date.fromisoformat(rows[-1]["date"][:10])
    except (ValueError, IndexError):
        return max(1, int(len(rows) * 0.8))
    span_days = (d1 - d0).days
    if span_days < 1:
        return max(1, int(len(rows) * 0.8))
    cutoff = (d1 - timedelta(days=round(span_days * 0.2))).isoformat()
    cut = next((i for i, r in enumerate(rows) if r["date"][:10] >= cutoff), len(rows))
    return max(1, min(cut, len(rows) - 1))


def build(sport_id, out_dir=mg.MODELS):
    # Archive whatever is CURRENTLY on disk before it is overwritten below — an immutable
    # trail of every day's model, not just today's (docs/DECISIONS/0004). Best-effort: a
    # sport being built for the first time has nothing to archive yet, which is fine.
    try:
        governance.archive_model_version(sport_id)
    except OSError:
        pass
    rows = results_store.load(sport_id)
    if not rows:
        return None, "no results stored"
    rows.sort(key=lambda r: r["date"])
    rating, gaps = mg.fit_ratings(rows, record=True)
    lines = LADDER_LINES[scale_of(rows)]

    cut = _holdout_cut(rows)
    train, test = rows[:cut], rows[cut:]
    train_gaps, test_gaps = gaps[:cut], gaps[cut:]
    if len(test) >= 100:
        tr_fit = mg.fit_line(train, train_gaps)
        cal = calibrate(test, test_gaps, tr_fit,
                        mg.fit_bands(train, train_gaps, tr_fit),
                        lines, _appearances(train))
    else:
        cal = []
    fit = mg.fit_line(rows, gaps)
    bands = mg.fit_bands(rows, gaps, fit)

    # Aliases: every other name a team has appeared under, so an older spelling on the
    # book's card still resolves. Built from the store rather than hand-maintained.
    latest, aliases = mg.name_map(rows)
    model = {
        "sport_id": sport_id,
        "sport": tr.sport(sport_id, str(sport_id)),
        "games": len(rows),
        "teams": len(rating),
        "pool_count": len({p for p, _ in rating}),
        "first": min(r["date"] for r in rows),
        "last": max(r["date"] for r in rows),
        "leagues": sorted({r.get("league") for r in rows if r.get("league")})[:60],
        "sources": sorted({r.get("source") or "?" for r in rows}),
        "scale": scale_of(rows),
        # Declared by the adapter. Without it the model would answer questions asked in a
        # unit it does not measure — see engine/model_generic.HANDICAP_GROUPS.
        "unit": next((r["unit"] for r in rows if r.get("unit")), None),
        "line": {k: round(v, 6) if isinstance(v, float) else v
                 for k, v in fit.items()},
        "bands": bands,
        "calibration": cal,
        "calibration_holdout": {"train": len(train), "test": len(test),
                                # TRAIN's own date range, so "no chronological overlap
                                # with test" is a DIRECT, checkable fact rather than an
                                # inferred one — see tests/test_regression.py's
                                # test_a_model_is_admitted_only_by_held_out_calibration,
                                # which used to assert train_rows > test_rows as a proxy
                                # for this and broke the day a date-proportional split
                                # (docs/DECISIONS, pmc-2026-08-06-tennis-split) made that
                                # ratio no longer universally true (a sport whose recent
                                # collection is much denser than its archive, e.g. table
                                # tennis via the live watcher, can have MORE rows in its
                                # 20%-of-time test window than its 80%-of-time train one,
                                # while remaining a perfectly genuine, non-overlapping
                                # holdout — train_to <= from is the property that was
                                # actually being protected).
                                "train_from": train[0]["date"] if train else None,
                                "train_to": train[-1]["date"] if train else None,
                                "from": test[0]["date"] if test else None,
                                "to": test[-1]["date"] if test else None},
        "appearances": _appearances_by_pool(_appearances(rows), latest),
        "pools": _by_pool(rating, latest),
        "aliases": _aliases_by_pool(aliases, latest),
        # THE BOOK'S OWN PARTICIPANT IDS, where a source recorded them. The live watcher
        # takes them straight off the feed the card is built from, so for anything it
        # collected the fixture on today's card and the row in the store share a key that
        # no spelling can break — and name matching, with its fuzzy threshold and its
        # (Women)/U20 guard, does not have to be right for that fixture at all.
        "book_ids": _book_ids(rows, latest),
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{sport_id}.json"), "w") as f:
        json.dump(model, f, ensure_ascii=False)
    return model, None


def report(model):
    ok, why = mg.usable(model)
    name = model.get("sport") or model["sport_id"]
    print(f"\n=== {name} (spor {model['sport_id']}) ===")
    print(f"  birim: {model.get('unit') or '(beyan edilmedi, çıkarılacak)'}")
    print(f"  {model['games']} maç · {model['teams']} takım · "
          f"{len(model['pools'])} derece havuzu · "
          f"{model['first']} → {model['last']} · kaynak {', '.join(model['sources'])}")
    ln = model["line"]
    print(f"  beklenen fark = {ln['slope']:.5f} × derece farkı + {ln['intercept']:.3f}"
          f"   (ortalama |fark| {ln['mean_abs_margin']:.2f})")
    g = model["bands"][""]
    pooled = [k for k in model["bands"] if k]
    print(f"  {len(g)} bant · bant başına ~{g[0]['n']} maç · "
          f"beklenen fark {g[0]['lo']:+.2f} → {g[-1]['hi']:+.2f}"
          + (f" · {len(pooled)} havuzun kendi bantları var" if pooled else ""))
    ho = model.get("calibration_holdout") or {}
    if ho.get("test"):
        print(f"  kalibrasyon: {ho['train']} maçla fit, GÖRÜLMEMİŞ {ho['test']} maçta "
              f"sınandı ({ho['from']} → {ho['to']})")
    print(f"  {'çizgi':>7} {'model':>8} {'gerçek':>8} {'fark':>8}")
    for c in model["calibration"]:
        print(f"  +{c['line']:<6} {c['predicted']:>8.3f} {c['observed']:>8.3f} "
              f"{c['predicted'] - c['observed']:>+8.3f}")
    rated = sum(1 for pool in model["appearances"].values()
                for n in pool.values() if n >= mg.MIN_APPEARANCES)
    print(f"  {rated} takım/oyuncu {mg.MIN_APPEARANCES}+ maçla derecelendirildi "
          f"({model['teams']} içinden) — geri kalanı fiyatlanmaz")
    print(f"  -> {'KULLANILABİLİR' if ok else 'REDDEDİLDİ'}: {why}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", type=int, help="single sport id")
    ap.add_argument("--all", action="store_true", help="every sport in the store")
    args = ap.parse_args()

    have = results_store.summary()
    if not have:
        print("data/results is empty — run tools/collect_results.py first", file=sys.stderr)
        return 1
    sports = [args.sport] if args.sport else sorted(have)
    if args.sport and args.sport not in have:
        print(f"no results stored for sport {args.sport}", file=sys.stderr)
        return 1

    usable = []
    for sid in sports:
        model, err = build(sid)
        if err:
            print(f"sport {sid}: {err}", file=sys.stderr)
            continue
        if report(model):
            usable.append(sid)
    print(f"\nkullanılabilir modeller: {usable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
