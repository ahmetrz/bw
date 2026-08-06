"""ConfidencePrediction: the full, reportable record behind one candidate selection.

This is the platform brief's section 12 contract (estimated probability, uncertainty,
data quality, market reliability, model consensus, contradiction score, bookmaker odds,
implied probability, corrected probability, EV, 0-100 confidence, factors up/down, risks,
sources, model version, analysis time) assembled from what engine/rating.py and
engine/dataquality.py ALREADY compute — nothing here recomputes the probability or the
0-100 score differently. That is deliberate: hard rule 6 says the score is the model's
win probability discounted by evidence and NOTHING else, and rating.score() already has a
test proving it never reads price (tests/test_regression.py::test_score_never_reads_the_price).
This module adds the reporting layer around that number; it does not touch the number.

EV/implied-probability here are DIAGNOSTIC fields, reported for the analyst's reading, not
selection inputs — engine/combine.py filters and ranks on confidence_score and data
quality alone. Folding EV back into selection would repeat the mistake hard rule 6 exists
to prevent: a positive EV against a free public model usually means model error, not a
mispriced book (engine/edge.py's own docstring says the same thing for the same reason).
"""
import datetime

from engine import dataquality, rating

MODEL_VERSION_UNKNOWN = "bilinmiyor"


def model_version(pick):
    """A stable-ish tag for which model/fit produced this pick's probabilities.

    Not a semantic version — a content fingerprint: source + how much history stood
    behind it, so two picks from re-fits on different days are visibly different versions
    without a separate version registry to keep in sync by hand.
    """
    source = pick.get("model_source") or "?"
    n = pick.get("division_matches") or pick.get("model_n")
    if n:
        return f"{source}-{int(n)}g"
    return source


def implied_probability(odds):
    if not odds or odds <= 1.0:
        return None
    return round(1.0 / odds, 4)


def expected_value(model_prob, odds):
    """EV per unit stake at the given odds, from the MODEL's probability.

    Reported only — see module docstring. None when either input is missing rather than
    a fabricated 0.0, which would silently claim a fair-value bet.
    """
    if model_prob is None or not odds:
        return None
    return round(model_prob * odds - 1.0, 4)


def _consensus(pick, alt_probs=None):
    """Model-consensus / contradiction signals, when a second model ALSO reached this
    fixture. `alt_probs` is an optional second probability dict from a different source
    (e.g. the generic model, when a hand-written model was used and also priced the same
    fixture) — supplied by the caller, since resolving it needs the same model set
    engine/pick.py already loaded. With no second opinion available, both come back None
    rather than a fabricated "consensus" of one."""
    if not alt_probs:
        return None, None
    mine = pick.get("model_survival")
    alt_dir = alt_probs.get("_direction")
    same_direction = alt_dir is None or alt_dir == pick.get("direction")
    contradiction = 0.0 if same_direction else 1.0
    consensus = 1.0 - contradiction
    return consensus, contradiction


def factors(pick, dq, score_info=None):
    """Plain-language factors up/down, built from the SAME numbers already on the pick —
    not a second judgement, a translation of the existing evidence breakdown into text a
    reader does not have to reverse-engineer from a score.

    `score_info` is rating.score()'s own return value, passed in by build() rather than
    re-read from the pick dict — a pick is only mutated with evidence_pct/etc. by
    rating.annotate(), which build()'s caller may or may not have run first, and this
    function must give the same answer either way.
    """
    up, down = [], []
    ev = (score_info or {}).get("evidence_pct", pick.get("evidence_pct"))
    if ev is not None:
        if ev >= 90:
            up.append(f"kanıt gücü yüksek ({ev:.0f}/100)")
        elif ev < 60:
            down.append(f"kanıt gücü düşük ({ev:.0f}/100)")
    name = pick.get("name_match")
    if name is not None and name < 0.999:
        down.append(f"isim eşleşmesi kesin değil ({name:.2f})")
    n = pick.get("model_n") or pick.get("division_matches")
    if n:
        if n >= dataquality.MIN_SAMPLE_FOR_FULL_MARKS:
            up.append(f"geniş örneklem ({int(n)} maç)")
        elif n < 400:
            down.append(f"dar örneklem ({int(n)} maç)")
    ladder_depth = pick.get("ladder_available")
    if ladder_depth and ladder_depth >= 3:
        up.append("güvenlik merdiveninde birden fazla basamak mevcuttu")
    for r in dq["reasons"]:
        if r["severity"] in (dataquality.SEVERITY_MAJOR, dataquality.SEVERITY_CRITICAL):
            down.append(r["detail"])
    return {"up": up, "down": down}


def risks(pick, dq):
    out = []
    settlement = pick.get("settlement") or {}
    if settlement.get("needs_confirmation"):
        out.append("sonuçlanma kuralı bu pazar için teyit edilmedi")
    if dq["score"] < 70:
        out.append("veri kalite puanı düşük")
    if (pick.get("ladder_available") or 0) <= 1:
        out.append("güvenlik merdiveninde tek basamak vardı — alternatifsiz seçim")
    return out


def annotate(picks, floor=None):
    """Attach a ConfidencePrediction to every pick as pick['_confidence'], in place —
    same mutate-and-return convention as engine/rating.annotate(). Downstream code
    (engine/referee.py, engine/combine.py) reads pick['_confidence'] directly rather
    than threading a parallel list through every call."""
    for p in picks:
        p["_confidence"] = build(p, floor)
    return picks


def build(pick, floor=None, alt_probs=None, now=None):
    """The full ConfidencePrediction for one pick. Pure function of its inputs — no I/O,
    so it is trivially unit-testable and safe to call from both the daily pipeline and a
    what-if / backtest context."""
    dq = dataquality.assess(pick)
    score_info = rating.score(pick, floor)          # UNCHANGED — hard rule 6's number
    consensus, contradiction = _consensus(pick, alt_probs)
    odds = pick.get("odds")
    model_prob = pick.get("model_survival")
    imp = implied_probability(odds)
    ev = expected_value(model_prob, odds)

    return {
        "estimated_probability": model_prob,
        "model_uncertainty": round(1.0 - (score_info["evidence_pct"] / 100.0), 3),
        "data_quality": dq,
        "market_reliability": None if (pick.get("settlement") or {}).get(
            "needs_confirmation") else "confirmed",
        "model_consensus": consensus,
        "contradiction_score": contradiction,
        "bookmaker_odds": odds,
        "implied_probability": imp,
        # No non-proportional de-vig method is in production (DATA_CONTRACT.md: only
        # proportional de-vig is implemented, and that yields the SAME self-edge for
        # every selection in a market, which is not an informative per-selection
        # correction) — reported as None rather than a number that would look precise
        # and mean nothing extra beyond the market's overround, which is already
        # reported separately as margin_score.
        "corrected_probability": None,
        "expected_value": ev,
        "confidence_score": score_info["score"],
        "confidence_band": score_info["band"],
        "factors": factors(pick, dq, score_info),
        "risks": risks(pick, dq),
        "data_sources": sorted({s for s in (pick.get("model_source"),) if s}),
        "model_version": model_version(pick),
        "analysis_timestamp": (now or datetime.datetime.now(datetime.timezone.utc)
                               ).isoformat(),
    }
