"""Data Quality Score: what stands behind ONE pick, reason-coded and auditable.

Reuses the signals engine/rating.py already computes (name_match, model_n,
division_matches) rather than inventing a second copy of them — the discount rating.py
applies IS a data-quality judgement already, just not broken out by reason. This module
is the transparency layer the platform brief (section 8) asks for: the SAME underlying
facts, decomposed into named components with reason codes, so a low score can be argued
with instead of just observed.

Deliberately does not read odds/price for the SCORE itself (hard rule 6's discipline
extends here: data quality describes the EVIDENCE behind a model call, not whether the
book's price looks good) — it does report odds/staleness presence as completeness
checks, which is a different thing from letting price influence a probability.

Nothing here is fabricated. A component this codebase cannot measure (lineups, cross-
source consistency, structured injury data) is reported as UNAVAILABLE with the reason
code the platform brief names, never guessed at.
"""
import functools
import math

# Reason codes from the platform brief (section 8), used verbatim so a downstream reader
# (the referee board, the web panel) can match on a fixed vocabulary.
CRITICAL_ODDS_MISSING = "CRITICAL_ODDS_MISSING"
STALE_EVENT_DATA = "STALE_EVENT_DATA"
PLAYER_IDENTITY_UNCERTAIN = "PLAYER_IDENTITY_UNCERTAIN"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
MARKET_MAPPING_UNVERIFIED = "MARKET_MAPPING_UNVERIFIED"
LINEUP_DATA_UNAVAILABLE = "LINEUP_DATA_UNAVAILABLE"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
RESULT_VERIFICATION_UNAVAILABLE = "RESULT_VERIFICATION_UNAVAILABLE"

SEVERITY_CRITICAL = "critical"   # selection must not enter the combine
SEVERITY_MAJOR = "major"         # confidence discounted hard
SEVERITY_MINOR = "minor"         # noted, small discount
SEVERITY_INFO = "info"           # disclosed, no discount — an honest "we don't have this"

# A sample this thin is not a measurement (mirrors engine/model_generic.MIN_APPEARANCES /
# MIN_RESULTS in spirit; kept as an independent constant because data-quality reporting
# must survive those two changing independently of each other).
MIN_SAMPLE_FOR_FULL_MARKS = 1500
NAME_MATCH_FULL_MARKS = 1.00
NAME_MATCH_FLOOR = 0.80          # engine/model_generic._fuzzy's own cutoff; below this a
                                  # match is refused outright and never reaches this module


def _name_identity(pick):
    """PLAYER_IDENTITY_UNCERTAIN component. An exact/book-id match is full marks."""
    name = pick.get("name_match")
    if name is None:
        return 1.0, None   # no name-matching was involved (e.g. book id resolved it)
    if name >= 0.999:
        return 1.0, None
    frac = max(0.0, min(1.0, (name - NAME_MATCH_FLOOR) / (1.0 - NAME_MATCH_FLOOR)))
    severity = SEVERITY_MAJOR if frac < 0.5 else SEVERITY_MINOR
    return frac, {
        "code": PLAYER_IDENTITY_UNCERTAIN, "severity": severity,
        "detail": f"isim eşleşmesi {name:.2f} (tam eşleşme değil)",
    }


def _sample_size(pick):
    """INSUFFICIENT_SAMPLE component, from whichever sample-size signal the pick carries."""
    n = pick.get("model_n") or pick.get("division_matches")
    if not n:
        return 0.6, {
            "code": INSUFFICIENT_SAMPLE, "severity": SEVERITY_INFO,
            "detail": "örneklem büyüklüğü bu seçim için raporlanmadı",
        }
    frac = min(1.0, n / MIN_SAMPLE_FOR_FULL_MARKS)
    if frac >= 1.0:
        return 1.0, None
    severity = SEVERITY_MAJOR if n < 400 else SEVERITY_MINOR
    return frac, {
        "code": INSUFFICIENT_SAMPLE, "severity": severity,
        "detail": f"{int(n)} maçlık örneklem (tam güven için {MIN_SAMPLE_FOR_FULL_MARKS}+)",
    }


def _odds_completeness(pick):
    """CRITICAL_ODDS_MISSING — a safety-net check. pick.py's own contract already
    requires odds on every emitted selection, so this should never actually fire; it
    exists because a report that cannot fail a check is not auditing anything."""
    odds = pick.get("odds")
    if not odds or odds <= 1.0:
        return 0.0, {
            "code": CRITICAL_ODDS_MISSING, "severity": SEVERITY_CRITICAL,
            "detail": "oran eksik veya geçersiz",
        }
    return 1.0, None


def _staleness(pick):
    """STALE_EVENT_DATA. Betwinner's own feed carries no per-selection changedAt
    (engine/bwfeed.py: changed_at is always None), so this is honestly reported as
    unmeasurable for the primary source rather than assumed fresh."""
    staleness = pick.get("staleness_seconds")
    if staleness is None:
        return 0.9, {
            "code": STALE_EVENT_DATA, "severity": SEVERITY_INFO,
            "detail": "kaynak seçim bazlı güncellenme zamanı yayınlamıyor; tazelik "
                      "doğrudan ölçülemiyor",
        }
    minutes = staleness / 60.0
    if minutes <= 5:
        return 1.0, None
    frac = max(0.0, 1.0 - (minutes - 5) / 30.0)
    severity = SEVERITY_MAJOR if minutes > 20 else SEVERITY_MINOR
    return frac, {
        "code": STALE_EVENT_DATA, "severity": severity,
        "detail": f"{minutes:.0f} dakikadır güncellenmemiş",
    }


def _market_mapping(pick):
    """MARKET_MAPPING_UNVERIFIED. settlement.needs_confirmation is the existing signal
    for "we are not certain how this market settles" — reused rather than duplicated."""
    settlement = pick.get("settlement") or {}
    if not settlement.get("needs_confirmation"):
        return 1.0, None
    return 0.7, {
        "code": MARKET_MAPPING_UNVERIFIED, "severity": SEVERITY_MINOR,
        "detail": settlement.get("detail") or "bu pazarın sonuçlanma kuralı teyit edilmedi",
    }


@functools.lru_cache(maxsize=1)
def _coverage_summary():
    """results_store.summary() re-reads and re-parses every data/results/<sport>.jsonl
    file on every call — deliberately, since it is normally called once per pipeline run
    (tools/make_method_page.py, tools/collect_results.py --list). Calling it once PER
    PICK here would turn an O(picks) pipeline into O(picks x total_result_rows). Cached
    for the lifetime of the process; a long-running process that also runs
    tools/collect_results.py mid-run should call _coverage_summary.cache_clear()."""
    from engine import results_store
    return results_store.summary()


def _result_verifiability(pick):
    """RESULT_VERIFICATION_UNAVAILABLE. Distinct from market mapping: this asks whether
    a settled outcome can be independently checked at all (results_store coverage for the
    sport), not whether the settlement RULE is confirmed."""
    sport_id = pick.get("sport_id")
    have = _coverage_summary().get(sport_id)
    if have and have.get("games", 0) >= 100:
        return 1.0, None
    return 0.5, {
        "code": RESULT_VERIFICATION_UNAVAILABLE, "severity": SEVERITY_MINOR,
        "detail": "bu spor için sonuç doğrulama kaynağı zayıf veya yok",
    }


# Always-unavailable components: honestly disclosed rather than silently omitted, per the
# platform brief's "eksik veriyi uydurma" rule. Every pick gets these two INFO-severity
# reasons attached, because the platform genuinely has neither source today (section 9's
# "Kadro durumu / Eksikler" and section 8's cross-source-consistency check both need a
# second independent source of the SAME fact, and this system deliberately has one feed).
STRUCTURAL_GAPS = (
    {"code": LINEUP_DATA_UNAVAILABLE, "severity": SEVERITY_INFO,
     "detail": "kadro/sakatlık verisi için ücretsiz, güvenilir bir kaynak entegre değil"},
    {"code": SOURCE_CONFLICT, "severity": SEVERITY_INFO,
     "detail": "tek oran kaynağı (Betwinner) kullanılıyor; çapraz kaynak tutarlılığı "
               "kontrol edilemiyor"},
)

WEIGHTS = {
    "identity": 0.30, "sample": 0.30, "odds": 0.15, "staleness": 0.10, "market": 0.15,
}


def assess(pick):
    """DataQualityAssessment for one pick: {score, reasons, components}.

    `score` is 0-100. This is a REPORTING score — it feeds engine/confidence.py's
    discount alongside (not instead of) rating.py's own evidence discount, and it never
    substitutes for rating.py's score as the ranking/selection signal.
    """
    identity, r1 = _name_identity(pick)
    sample, r2 = _sample_size(pick)
    odds, r3 = _odds_completeness(pick)
    stale, r4 = _staleness(pick)
    market, r5 = _market_mapping(pick)
    verify, r6 = _result_verifiability(pick)

    components = {
        "identity": round(identity, 3), "sample": round(sample, 3),
        "odds": round(odds, 3), "staleness": round(stale, 3), "market": round(market, 3),
        "result_verifiability": round(verify, 3),
    }
    weighted = sum(WEIGHTS[k] * components[k] for k in WEIGHTS)
    # result_verifiability is disclosed but not weighted into the score — it describes
    # the platform's ability to SETTLE the pick later, not the quality of the pick now.
    score = round(100.0 * weighted, 1)

    reasons = [r for r in (r1, r2, r3, r4, r5, r6) if r] + list(STRUCTURAL_GAPS)
    critical = any(r["severity"] == SEVERITY_CRITICAL for r in reasons)
    return {
        "score": 0.0 if critical else score,
        "blocks_combine": critical,
        "components": components,
        "reasons": reasons,
    }
