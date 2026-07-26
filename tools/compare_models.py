#!/usr/bin/env python3
"""Run the hand-written and generic models for a sport over the SAME card, side by side.

    python tools/compare_models.py --sport 10 --input data/betwinner_daily.json.gz

WHY THIS EXISTS. `MODELLED_SPORTS` in engine/pick.py is the list of hand-written models
and it is meant to shrink: every sport that goes through engine/model_generic.py is
admitted by a HELD-OUT calibration, and a hand-written one is admitted by somebody having
written it. Hard rule 8 says a model is wired in on its calibration rather than its reach,
so on paper the generic version should always win.

On paper is not enough to switch a live card on. A model with a better calibration that
reaches a third of the fixtures is not obviously the better product, and the two can
disagree about DIRECTION on the same match, which no calibration number will show you.
Football switched over on exactly this comparison: the generic model offered 52 selections
against 57 and found none the Elo model called the other way.

So this prints what a number cannot: reach, agreement, and every fixture where the two
models point in opposite directions. Those are the ones to read before switching.

NOTE ON THE COUNTS. Every fixture on the card is compared, including ones that have
already started — the daily run drops those, so its selection count for the same card is
lower and falls further behind as the card ages. That is deliberate: this is a comparison
between two models, and shrinking the sample to whatever has not kicked off yet would make
it depend on when you happened to run it.
"""
import argparse
import collections
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import (bwfeed, model_generic, model_tt, pick, setka,  # noqa: E402
                    simulated, tr)


def load(path):
    raw = gzip.open(path, "rb").read() if path.endswith(".gz") else open(path, "rb").read()
    return json.loads(raw)


def hand_written(sport_id):
    """(probs function, label) for the sport's hand-written model, or None."""
    if sport_id == 10:
        model = model_tt.load()
        if not model:
            return None
        index = model_tt.build_player_index(setka.ratings())

        def probs(home, away, _row):
            return model_tt.lookup(model, index, home, away)
        return probs, f"elle yazılmış ({model['samples']} örnek)"
    return None


def generic_for(sport_id):
    model = model_generic.load(sport_id)
    ok, why = model_generic.usable(model)
    if not ok:
        return None, why

    def probs(home, away, row):
        return model_generic.lookup(model, home, away,
                                    home_id=row.get("p1_id"), away_id=row.get("p2_id"))
    return probs, why


def selections(rows, sport_id, probs_fn):
    """{match_id: chosen selection} using the real ladder and the real gates."""
    by_match = collections.defaultdict(list)
    for r in rows:
        if r.get("sub_game") or r.get("sport_id") != sport_id:
            continue
        by_match[r.get("match_id", r["fixture_id"])].append(r)

    out, priced = {}, 0
    for mid, match_rows in by_match.items():
        sample = match_rows[0]
        probs, score = probs_fn(sample.get("p1"), sample.get("p2"), sample)
        if not probs or score < 0.86:
            continue
        priced += 1
        chosen = pick.best(match_rows, sport_id, probs)
        if chosen:
            chosen["_name_score"] = round(score, 3)
            out[mid] = chosen
    return out, priced, len(by_match)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", type=int, required=True)
    ap.add_argument("--input", required=True)
    args = ap.parse_args()

    rows = bwfeed.normalize(load(args.input))
    fake = simulated.load()
    if fake:
        rows = [r for r in rows if (r.get("sport_id"), r.get("league")) not in fake]

    hand = hand_written(args.sport)
    gen_fn, gen_why = generic_for(args.sport)
    if not hand:
        print(f"sport {args.sport} has no hand-written model — nothing to compare against")
        return 1
    if not gen_fn:
        print(f"generic model not admitted: {gen_why}")
        return 1

    hand_fn, hand_label = hand
    a, a_priced, total = selections(rows, args.sport, hand_fn)
    b, b_priced, _ = selections(rows, args.sport, gen_fn)

    name = tr.sport(args.sport, str(args.sport))
    print(f"\n=== {name}: kartta {total} maç\n")
    print(f"  {'':<22}{'fiyatlanan':>12}{'seçim':>8}{'ort. olasılık':>15}")
    for label, sel, priced in ((hand_label, a, a_priced), (f"genel — {gen_why}", b, b_priced)):
        avg = (sum(s["model_survival"] for s in sel.values()) / len(sel)) if sel else 0.0
        print(f"  {label[:21]:<22}{priced:>12}{len(sel):>8}{avg:>14.1%}")

    both = set(a) & set(b)
    only_a, only_b = set(a) - set(b), set(b) - set(a)
    print(f"\n  ikisi de: {len(both)} · yalnız elle yazılmış: {len(only_a)} · "
          f"yalnız genel: {len(only_b)}")

    disagree = [m for m in both if a[m].get("direction") != b[m].get("direction")]
    print(f"  aynı maçta TERS yön: {len(disagree)}")
    for mid in disagree[:12]:
        x, y = a[mid], b[mid]
        print(f"    {x['p1']} v {x['p2']}")
        print(f"      elle: {x['direction']:<6} {tr.pick(x):<38} %{x['model_survival']:.1%}"
              .replace("%0", "%").replace("%", " ") + f"  @{x['odds']}")
        print(f"      genel: {y['direction']:<6} {tr.pick(y):<38} "
              f"{y['model_survival']:.1%}  @{y['odds']}")

    same_dir = [m for m in both if a[m].get("direction") == b[m].get("direction")]
    same_rung = [m for m in same_dir
                 if a[m].get("market_key") == b[m].get("market_key")]
    print(f"  aynı yön: {len(same_dir)} · bunlardan aynı basamak: {len(same_rung)}")
    if config.MIN_MODEL_SURVIVAL:
        print(f"\n  (güven tabanı %{config.MIN_MODEL_SURVIVAL:.0%}, "
              f"min oran {config.MIN_ODDS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
