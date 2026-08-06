"""The daily combine: select a SUBSET of eligible football/tennis picks into one slip,
score it multi-objectively, and say so honestly when no subset clears the bar.

Pipeline (see tools/daily_combine.py for the runnable entrypoint):
    picks (engine.pick.for_fixtures output)
      -> confidence.annotate()      # attach the 0-100 score + full report per pick
      -> eligible()                 # hard gates: sport scope, 80 floor, not started, ...
      -> referee.review_all()       # 10 judges; any veto removes a leg
      -> optimize()                 # beam search over what survives the board
      -> settle_combine() later, once results are in

WHY BEAM SEARCH (brief section 15 explicitly allows "beam search" among other methods):
a brute-force search over subsets is 2^n, and a full day's football+tennis card can
plausibly offer several dozen eligible legs. A single greedy fill (sort by confidence,
take everything that keeps the combined-probability floor) is what section 15 explicitly
warns against producing — it cannot trade a marginal 31st leg against the probability it
costs, it can only accept or reject in a fixed order. Beam search keeps a bounded set of
the best PARTIAL combines seen at each step, which lets a leg be skipped now and the
option reconsidered against a different combination, while staying far cheaper than
brute force. Integer programming would find a provably optimal solution for a LINEAR
objective, but the objective below is deliberately non-linear (log-scaled odds utility,
sqrt-scaled count utility, a multiplicative probability floor) because the brief asks for
diminishing returns on leg count and odds, not a linear trade — so IP was not the fit.
"""
import datetime
import math

import config
from engine import coupon, grade, referee


def _parse_start(start):
    """Picks carry `start` as an ISO string (engine/bwfeed.py's own row shape) — parsed
    defensively since a malformed or missing timestamp must exclude a leg, never crash
    the whole combine build."""
    if not start:
        return None
    if isinstance(start, datetime.datetime):
        return start
    try:
        return datetime.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None

MAX_REASONABLE_LEGS = coupon.MAX_EVENTS   # 50 — same ceiling the book itself enforces


def eligible(picks, now):
    """Hard gates before a pick may even be CONSIDERED for the combine. Every check here
    is a yes/no gate, not a scored preference — scoring/trade-offs are optimize()'s job.
    """
    out, excluded = [], []
    for p in picks:
        conf = p.get("_confidence")
        reasons = []
        if p.get("sport_id") not in config.COMBINE_SPORTS:
            reasons.append("kapsam dışı spor (yalnızca futbol+tenis)")
        if not conf:
            reasons.append("güven değerlendirmesi hesaplanmadı")
        elif conf["confidence_score"] < config.MIN_COMBINE_CONFIDENCE:
            reasons.append(f"güven puanı {conf['confidence_score']:.1f} < "
                          f"{config.MIN_COMBINE_CONFIDENCE:.0f} eşiği")
        elif conf["data_quality"]["blocks_combine"]:
            reasons.append("veri kalitesi kritik eşiğin altında")
        start = _parse_start(p.get("start"))
        if start is None:
            reasons.append("başlangıç zamanı okunamadı")
        elif start <= now:
            reasons.append("karşılaşma zaten başlamış veya analiz penceresi dışında")
        if not p.get("odds") or p["odds"] < config.MIN_ODDS:
            reasons.append("oran eşiği karşılanmıyor")
        if reasons:
            excluded.append({"match": f"{p.get('p1')} v {p.get('p2')}", "reasons": reasons})
        else:
            out.append(p)
    return out, excluded


def _combined_probability(legs):
    p = 1.0
    for leg in legs:
        p *= leg.get("model_survival") or 0.0
    return p


def _combined_odds(legs):
    o = 1.0
    for leg in legs:
        o *= leg.get("odds") or 1.0
    return o


def confidence_interval(legs):
    """A heuristic band for the combine's combined probability, propagated from each
    leg's own evidence discount. NOT a rigorous statistical interval (no closed form
    fits the discounted-Elo/Laplace-capped pipeline cleanly) — a conservative-low and
    optimistic-high bound built from the SAME evidence_penalty rating.py already reports,
    so it is at least internally consistent with the number it is bracketing. Reported to
    the operator as a band, not as a precise CI, and documented as such in
    docs/COUPON_OPTIMIZATION.md.
    """
    lo = hi = 1.0
    for leg in legs:
        p = leg.get("model_survival") or 0.0
        penalty_pts = leg.get("evidence_penalty") or 0.0   # points out of 100
        spread = penalty_pts / 100.0
        lo *= max(0.0, p - spread)
        hi *= min(1.0, p + spread * 0.3)   # upside is bounded tighter — evidence being
                                            # thin argues for caution, not for a symmetric
                                            # "could also be better than stated" swing
    return round(lo, 4), round(hi, 4)


def _correlation_penalty(legs):
    if not legs:
        return 0.0
    import collections
    leagues = collections.Counter(l.get("league") for l in legs if l.get("league"))
    if not leagues:
        return 0.0
    _, top_n = leagues.most_common(1)[0]
    share = top_n / len(legs)
    return max(0.0, share - config.COMBINE_MAX_LEAGUE_SHARE)


def _objective(legs):
    """Scalarised multi-objective score used ONLY to guide the search — the report shown
    to the operator presents the underlying figures (count, total odds, combined
    probability) separately and in plain terms, never this composite number."""
    if not legs:
        return 0.0
    n = len(legs)
    avg_conf = sum((l.get("_confidence") or {}).get("confidence_score", 0) for l in legs
                  ) / n / 100.0
    prob = _combined_probability(legs)
    total_odds = _combined_odds(legs)
    count_utility = math.sqrt(n) / math.sqrt(MAX_REASONABLE_LEGS)
    odds_utility = math.log(max(total_odds, 1.0001)) / math.log(MAX_REASONABLE_LEGS)
    corr_penalty = _correlation_penalty(legs)
    return (0.35 * avg_conf + 0.25 * prob + 0.20 * count_utility + 0.15 * odds_utility
           - 0.15 * corr_penalty)


def optimize(candidates, beam_width=None):
    """Beam search over which subset of `candidates` (already-eligible picks) to combine.

    Returns [] when no non-empty subset clears MIN_COMBINE_COMBINED_PROBABILITY — the
    empty combine is always in the search space and wins whenever nothing else scores
    higher, which is how "no combine today" falls out of the SAME code path as a normal
    day rather than needing a special case.
    """
    beam_width = beam_width or config.COMBINE_BEAM_WIDTH
    ordered = sorted(candidates,
                     key=lambda p: -(p.get("_confidence") or {}).get("confidence_score", 0))
    n = len(ordered)

    def legs_of(state):
        return [ordered[i] for i in state]

    beam = {frozenset()}
    best_state, best_score = frozenset(), _objective([])
    for idx in range(n):
        leg = ordered[idx]
        new_states = set(beam)
        for state in beam:
            used_matches = {ordered[i].get("match_id", ordered[i].get("fixture_id"))
                            for i in state}
            if leg.get("match_id", leg.get("fixture_id")) in used_matches:
                continue
            candidate = state | {idx}
            if _combined_probability(legs_of(candidate)) >= \
                    config.MIN_COMBINE_COMBINED_PROBABILITY:
                new_states.add(candidate)
        scored = sorted(new_states, key=lambda s: -_objective(legs_of(s)))
        beam = set(scored[:beam_width])
        if scored:
            top_score = _objective(legs_of(scored[0]))
            if top_score > best_score:
                best_state, best_score = scored[0], top_score
    return legs_of(best_state)


def build_combine(picks, now, context=None):
    """The full pipeline: eligible() -> referee.review_all() -> optimize() -> report.

    Returns a dict matching section 15's reporting requirements: counts, combined odds,
    combined probability + band, per-leg contribution, borderline/vetoed selections, and
    a plain-language reason for the shape of the result. Never raises on "no combine" —
    that is `combine["legs"] == []`, a normal, first-class, expected-to-happen outcome
    (brief section 2 / hard rule 6 of the test list: "Kupon üretmek zorunlu değildir").
    """
    context = context or {}
    elig, gate_excluded = eligible(picks, now)
    if not elig:
        return _empty_report(picks, gate_excluded, [], None, "aday yok: hiçbir seçim "
                             "giriş eşiklerini geçemedi")

    per_leg_verdicts, correlation, final = referee.review_all(elig, [p["_confidence"] for p in elig],
                                                              context)
    vetoed, survivors = [], []
    for p, verdicts, decision in zip(elig, per_leg_verdicts, final["decisions"]):
        # Carried on the pick itself (not a parallel list) so it survives optimize()'s
        # subset selection below and reaches the final report on whichever legs are
        # actually chosen — the "Hakem Kurulu" screen renders exactly this.
        p["_referee"] = {"verdicts": verdicts, "decision": decision,
                         "correlation_flagged": decision["correlation_flagged"]}
        if decision["include"]:
            survivors.append(p)
        else:
            vetoed.append({"match": decision["match"],
                          "vetoes": [v["note"] for v in decision["vetoes"]],
                          "all_verdicts": verdicts})
    if not survivors:
        return _empty_report(picks, gate_excluded, vetoed, correlation,
                             "aday yok: hakem kurulu tüm adayları veto etti",
                             eligible_count=len(elig))

    chosen = optimize(survivors)
    if not chosen:
        return _empty_report(
            picks, gate_excluded, vetoed, correlation,
            f"{len(survivors)} hakem onaylı aday vardı ama hiçbir alt küme minimum "
            f"birleşik olasılık eşiğini ({config.MIN_COMBINE_COMBINED_PROBABILITY:.0%}) "
            "karşılamadı", eligible_count=len(elig), referee_approved_count=len(survivors))

    chosen_ids = {c.get("match_id", c.get("fixture_id")) for c in chosen}
    borderline = [p for p in survivors
                 if p.get("match_id", p.get("fixture_id")) not in chosen_ids]
    lo, hi = confidence_interval(chosen)
    return {
        "generated_at": now.isoformat() if hasattr(now, "isoformat") else now,
        "legs": chosen,
        "leg_count": len(chosen),
        "combined_odds": round(_combined_odds(chosen), 3),
        "combined_probability": round(_combined_probability(chosen), 4),
        "combined_probability_band": {"low": lo, "high": hi},
        "avg_confidence": round(sum(c["_confidence"]["confidence_score"] for c in chosen)
                                / len(chosen), 1),
        "scanned_count": len(picks),
        "eligible_count": len(elig),
        "referee_approved_count": len(survivors),
        "gate_excluded": gate_excluded,
        "vetoed": vetoed,
        "borderline": [{"match": f"{p.get('p1')} v {p.get('p2')}",
                       "confidence": p["_confidence"]["confidence_score"]}
                      for p in sorted(borderline,
                                      key=lambda p: -p["_confidence"]["confidence_score"])],
        "correlation_notes": correlation["notes"],
        "why": _why(chosen, survivors, correlation),
    }


def _empty_report(picks, gate_excluded, vetoed, correlation, why, eligible_count=0,
                  referee_approved_count=0):
    return {
        "legs": [], "leg_count": 0, "combined_odds": None, "combined_probability": None,
        "combined_probability_band": None, "avg_confidence": None,
        "scanned_count": len(picks), "eligible_count": eligible_count,
        "referee_approved_count": referee_approved_count,
        "gate_excluded": gate_excluded, "vetoed": vetoed,
        "correlation_notes": (correlation or {}).get("notes", []),
        "borderline": [], "why": why,
    }


def _why(chosen, survivors, correlation):
    parts = [f"{len(chosen)} seçim, {len(survivors)} hakem onaylı adaydan seçildi"]
    if len(chosen) < len(survivors):
        parts.append("daha fazla seçim eklemek birleşik olasılığı ürünün anlamlı "
                     "kabul ettiği eşiğin altına düşürüyordu")
    if correlation["notes"]:
        parts.append("korelasyon notları: " + "; ".join(correlation["notes"]))
    return ". ".join(parts) + "."


# ------------------------------------------------------------------- combine settlement

def settle_combine(graded_legs):
    """Grade a WHOLE accumulator from its already-graded legs.

    Nothing in engine/grade.py does this — it grades one leg. Convention used (industry-
    standard accumulator settlement, applied here since Betwinner's OWN multi-leg push
    convention is unverified — engine/settlement.py's OPEN_QUESTIONS already lists this):
      * any LOSS leg -> the whole combine loses, full stake gone.
      * a PUSH leg is removed from the odds product (treated as odds=1.0), stake carries.
      * a HALF leg (quarter-line, half stake decided) contributes at the AVERAGE of its
        full odds and a push: (odds + 1) / 2 — half the notional stake won at the leg's
        price, half pushed.
      * any leg still pending -> the whole combine is pending; no partial verdict.
    """
    if any(l.get("result") is None for l in graded_legs):
        return {"result": "pending", "multiplier": None, "needs_confirmation": True}
    if any(l.get("result") == grade.LOSS for l in graded_legs):
        return {"result": grade.LOSS, "multiplier": 0.0,
               "needs_confirmation": False}
    multiplier = 1.0
    for leg in graded_legs:
        odds = leg.get("odds") or 1.0
        if leg["result"] == grade.WIN:
            multiplier *= odds
        elif leg["result"] == grade.HALF:
            multiplier *= (odds + 1.0) / 2.0
        # PUSH: multiplier unchanged (equivalent to *= 1.0)
    return {
        "result": grade.WIN, "multiplier": round(multiplier, 4),
        # Betwinner's own push/void convention inside one multi-leg slip has not been
        # independently confirmed (engine/settlement.py OPEN_QUESTIONS) — the figure above
        # is the standard industry convention, flagged rather than asserted as certain.
        "needs_confirmation": any(l["result"] in (grade.PUSH, grade.HALF)
                                  for l in graded_legs),
    }


# Analytical only — see hard prohibition on real-money features. This is a notional unit
# used purely to report a hypothetical ROI figure on the performance lab pages, exactly
# like engine/stake.py's existing flat-unit convention for the singles list; no real
# amount is ever suggested, no account is ever touched.
COMBINE_STAKE_UNITS = 1.0
