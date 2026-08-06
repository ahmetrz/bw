"""The referee board: ten independent, deterministic, rule-based checks over one candidate
selection (and, for the two board-level judges, over the whole candidate list together).

NO EXTERNAL LLM. Every judge below is arithmetic and lookups over data already computed
by engine/confidence.py, engine/dataquality.py, engine/rating.py and data/predictions.jsonl
— exactly what the platform brief asks for ("harici LLM kullanmamalıdır"). Each judge is a
plain function so it is unit-testable on its own, and each returns one Verdict:

    {"judge": name, "verdict": APPROVE|FLAG|VETO, "reason_code": str, "note": str,
     "confidence_penalty": float}   # points subtracted from the 0-100 score, 0 if none

A VETO from any judge removes the leg from the combine outright — no vote-counting, no
overriding a veto by consensus. This mirrors engine/coupon.py's own posture toward the
book's BANNED_FLAGS: one disqualifying fact is enough, regardless of how good everything
else about the leg looks.
"""
import collections

APPROVE, FLAG, VETO = "approve", "flag", "veto"

MIN_MEANINGFUL = 20   # same bar stats.html already uses before trusting a hit rate


# --------------------------------------------------------------------- per-leg judges

def data_quality_judge(pick, conf, context):
    """1. Veri Kalitesi Hakemi — vetoes on a critical gap, flags a shaky one."""
    dq = conf["data_quality"]
    if dq["blocks_combine"] or dq["score"] < 40:
        return _v("veri_kalitesi", VETO, "CRITICAL_ODDS_MISSING" if dq["blocks_combine"]
                  else "INSUFFICIENT_SAMPLE",
                  f"veri kalite puanı {dq['score']:.0f}/100 — kritik eşiğin altında")
    if dq["score"] < 65:
        return _v("veri_kalitesi", FLAG, "INSUFFICIENT_SAMPLE",
                  f"veri kalite puanı {dq['score']:.0f}/100 — sınırda", penalty=5.0)
    return _v("veri_kalitesi", APPROVE, None, f"veri kalite puanı {dq['score']:.0f}/100")


def statistical_consistency_judge(pick, conf, context):
    """2. İstatistiksel Tutarlılık Hakemi — the pick must carry every field hard rule 1
    requires and every number must be inside its own valid range. Checks the SHAPE of the
    evidence, never the price (hard rule 6) — a consistency judge that read the odds
    against the model's probability would just be re-deriving "edge" and calling it
    quality control."""
    required = ("odds", "model_survival", "market_type", "sport_id")
    missing = [f for f in required if pick.get(f) is None]
    if missing:
        return _v("istatistiksel_tutarlilik", VETO, "MARKET_MAPPING_UNVERIFIED",
                  f"eksik alan(lar): {', '.join(missing)}")
    p = pick["model_survival"]
    if not (0.0 <= p <= 1.0):
        return _v("istatistiksel_tutarlilik", VETO, "MARKET_MAPPING_UNVERIFIED",
                  f"model olasılığı aralık dışı: {p}")
    ev_pct = conf.get("model_uncertainty")
    if ev_pct is not None and not (0.0 <= ev_pct <= 1.0):
        return _v("istatistiksel_tutarlilik", FLAG, "MARKET_MAPPING_UNVERIFIED",
                  "belirsizlik bileşeni aralık dışı", penalty=5.0)
    return _v("istatistiksel_tutarlilik", APPROVE, None, "alanlar ve aralıklar tutarlı")


def market_reliability_judge(pick, conf, context):
    """3. Pazar Güvenilirliği Hakemi — settlement confirmation plus, when history exists,
    whether THIS market type has actually been gradeable in practice."""
    settlement = pick.get("settlement") or {}
    if settlement.get("needs_confirmation"):
        return _v("pazar_guvenilirligi", FLAG, "RESULT_VERIFICATION_UNAVAILABLE",
                  settlement.get("detail") or "sonuçlanma kuralı teyit edilmedi",
                  penalty=8.0)
    hist = context.get("market_history", {}).get(pick.get("market_type"))
    if hist and hist["graded"] >= MIN_MEANINGFUL and hist["ungradeable_rate"] > 0.15:
        return _v("pazar_guvenilirligi", FLAG, "RESULT_VERIFICATION_UNAVAILABLE",
                  f"bu pazar geçmişte %{hist['ungradeable_rate']*100:.0f} oranında "
                  "notlandırılamamış", penalty=6.0)
    return _v("pazar_guvenilirligi", APPROVE, None, "pazar sonuçlanma kuralı net")


def overfitting_judge(pick, conf, context):
    """4. Overfitting Hakemi — the exact shape of this codebase's two worst historical
    bugs (table tennis's logistic extrapolated to 97% on a 3.30 shot; a basketball sign
    error claiming 90.4%): near-certainty claimed on a thin sample. A confident number is
    not a correct one (hard rule 8) — this judge is that rule applied per-leg rather than
    per-sport."""
    p = pick.get("model_survival") or 0.0
    n = pick.get("model_n") or pick.get("division_matches") or 0
    if p >= 0.97 and n < 1500:
        return _v("overfitting", VETO, "INSUFFICIENT_SAMPLE",
                  f"%{p*100:.1f} iddiası yalnızca {int(n)} maçlık örneğe dayanıyor — "
                  "aşırı öğrenme riski")
    if p >= 0.93 and n < 400:
        return _v("overfitting", FLAG, "INSUFFICIENT_SAMPLE",
                  f"%{p*100:.1f} iddiası {int(n)} maçlık dar örnekle destekleniyor",
                  penalty=6.0)
    return _v("overfitting", APPROVE, None, "iddia edilen olasılık örneklem büyüklüğüyle orantılı")


def recency_judge(pick, conf, context):
    """5. Haber ve Güncellik Hakemi — checks what CAN be checked (odds staleness) and is
    explicit about what cannot be: this platform has no injury/lineup/news feed, so it
    never claims to have vetted one (section 10/11's ban on treating unverified news as
    confirmed fact — the honest version of that rule is simply not claiming the check)."""
    dq = conf["data_quality"]
    stale = next((r for r in dq["reasons"] if r["code"] == "STALE_EVENT_DATA"
                 and r["severity"] != "info"), None)
    if stale:
        return _v("guncellik", FLAG, "STALE_EVENT_DATA", stale["detail"], penalty=5.0)
    return _v("guncellik", APPROVE, None,
              "veri tazeliği kontrol edildi; haber/kadro doğrulaması bu platformda yok "
              "(kaynak entegrasyonu yapılmadı)")


def odds_ev_judge(pick, conf, context):
    """7. Oran/EV Hakemi — NOT a value-hunting judge (hard rule 6). Re-verifies the odds
    gate independently (trust-but-verify, the same posture engine/coupon.py takes toward
    its own slip before handing it over), and flags an implausibly high computed EV as a
    likely MODEL problem rather than a bet to chase — engine/edge.py's own documented
    reading of what a large positive edge against a free public model usually means."""
    odds = pick.get("odds")
    if not odds or odds < 1.10:
        return _v("oran_ev", VETO, "CRITICAL_ODDS_MISSING",
                  f"oran {odds} — 1.10 eşiğinin altında")
    ev = conf.get("expected_value")
    if ev is not None and ev > 0.35:
        return _v("oran_ev", FLAG, "MARKET_MAPPING_UNVERIFIED",
                  f"hesaplanan EV +%{ev*100:.0f} — halka açık bir modelde bu büyüklükte "
                  "bir avantaj çoğunlukla model/veri hatasına işaret eder, gerçek bir "
                  "fırsat değil", penalty=10.0)
    return _v("oran_ev", APPROVE, None, "oran eşiği ve EV makul aralıkta")


def historical_performance_judge(pick, conf, context):
    """8. Geçmiş Performans Hakemi — has this confidence band, for this sport, actually
    hit what it claimed historically? Needs MIN_MEANINGFUL graded samples before it will
    say anything at all (same small-sample discipline stats.html already applies)."""
    band = context.get("calibration_by_sport", {}).get(pick.get("sport_id"))
    if not band or band.get("graded", 0) < MIN_MEANINGFUL:
        return _v("gecmis_performans", APPROVE, None,
                  "bu spor için henüz yeterli notlandırılmış geçmiş yok "
                  f"(<{MIN_MEANINGFUL}) — değerlendirme yapılmadı")
    gap = band["claimed"] - band["realised"]
    if gap > 0.10:
        return _v("gecmis_performans", VETO, "SOURCE_CONFLICT",
                  f"bu spor iddia edilenden %{gap*100:.0f} puan daha kötü gerçekleşiyor "
                  f"({band['graded']} notlandırılmış seçim)")
    if gap > 0.05:
        return _v("gecmis_performans", FLAG, "SOURCE_CONFLICT",
                  f"gerçekleşen isabet iddia edilenin %{gap*100:.0f} puan altında",
                  penalty=8.0)
    return _v("gecmis_performans", APPROVE, None,
              f"gerçekleşen isabet iddia edilenle uyumlu ({band['graded']} örnek)")


def result_verifiability_judge(pick, conf, context):
    """9. Sonuç Doğrulanabilirliği Hakemi — section 11's rule made concrete: a market
    this platform cannot independently verify the outcome of must not be treated as
    reliable, regardless of how confident the model is."""
    dq = conf["data_quality"]
    r = next((x for x in dq["reasons"] if x["code"] == "RESULT_VERIFICATION_UNAVAILABLE"),
             None)
    if r:
        return _v("sonuc_dogrulanabilirligi", VETO, "RESULT_VERIFICATION_UNAVAILABLE",
                  r["detail"])
    return _v("sonuc_dogrulanabilirligi", APPROVE, None,
              "bu spor için sonuç doğrulama kaynağı yeterli")


def _v(judge, verdict, reason_code, note, penalty=0.0):
    return {"judge": judge, "verdict": verdict, "reason_code": reason_code, "note": note,
            "confidence_penalty": penalty}


PER_LEG_JUDGES = (
    data_quality_judge, statistical_consistency_judge, market_reliability_judge,
    overfitting_judge, recency_judge, odds_ev_judge, historical_performance_judge,
    result_verifiability_judge,
)


# ----------------------------------------------------------------- board-level judges
# These two see the WHOLE candidate list, because a correlation or a final risk call
# cannot be made leg by leg — "is this leg too concentrated with the others" is
# meaningless without the others.

def correlation_judge(picks, confs, context):
    """6. Korelasyon ve Ortak Risk Hakemi — flags concentration risk across the whole
    candidate list, not a per-leg verdict. Section 15's explicit examples: same
    league/competition dominating the slip, the same participant appearing twice (should
    already be structurally impossible via one-pick-per-match, checked anyway — belt and
    braces, same posture as engine/coupon.py's own dedup), and one data/model source
    behind everything.
    """
    notes, flagged_idx = [], set()
    leagues = collections.Counter(p.get("league") for p in picks if p.get("league"))
    total = len(picks) or 1
    for league, n in leagues.items():
        if n >= 3 and n / total > 0.40:
            notes.append(f"'{league}' turnuvasından {n}/{total} seçim — yoğunlaşma riski")
            for i, p in enumerate(picks):
                if p.get("league") == league:
                    flagged_idx.add(i)

    participants = collections.Counter()
    for p in picks:
        for who in (p.get("p1_id") or p.get("p1"), p.get("p2_id") or p.get("p2")):
            if who:
                participants[who] += 1
    repeats = {who for who, n in participants.items() if n > 1}
    if repeats:
        notes.append(f"{len(repeats)} katılımcı kupon içinde birden fazla kez geçiyor")
        for i, p in enumerate(picks):
            if (p.get("p1_id") or p.get("p1")) in repeats or \
               (p.get("p2_id") or p.get("p2")) in repeats:
                flagged_idx.add(i)

    sources = collections.Counter(p.get("model_source") for p in picks)
    if sources and total >= 5:
        top_source, top_n = sources.most_common(1)[0]
        if top_n / total > 0.85:
            notes.append(f"seçimlerin %{top_n/total*100:.0f}'i tek bir model kaynağına "
                        f"({top_source}) dayanıyor — ortak veri kaynağı riski")

    return {"judge": "korelasyon", "notes": notes, "flagged_indices": sorted(flagged_idx)}


def final_risk_judge(picks, confs, per_leg_verdicts, correlation, context):
    """10. Nihai Risk Hakemi — synthesises everything above into one call per leg
    (include / exclude) plus a board-level publish/don't-publish recommendation. Runs
    LAST, sees everything, decides nothing on its own that the other nine did not already
    surface — a synthesiser, not an eleventh independent check."""
    decisions = []
    for i, (pick, verdicts) in enumerate(zip(picks, per_leg_verdicts)):
        vetoes = [v for v in verdicts if v["verdict"] == VETO]
        flags = [v for v in verdicts if v["verdict"] == FLAG]
        penalty = sum(v["confidence_penalty"] for v in verdicts)
        correlation_flagged = i in correlation["flagged_indices"]
        include = not vetoes
        decisions.append({
            "match": f"{pick.get('p1')} v {pick.get('p2')}",
            "include": include,
            "vetoes": vetoes,
            "flags": flags,
            "correlation_flagged": correlation_flagged,
            "confidence_penalty_total": round(penalty, 1),
            "adjusted_confidence": round(max(0.0, confs[i]["confidence_score"] - penalty), 1),
        })
    n_in = sum(1 for d in decisions if d["include"])
    return {
        "judge": "nihai_risk",
        "decisions": decisions,
        "eligible_count": n_in,
        "publish": n_in > 0,
        "note": (f"{n_in}/{len(picks)} seçim kurul onayından geçti"
                if picks else "değerlendirilecek aday yok"),
    }


def review_all(picks, confs, context=None):
    """Run the whole board over a candidate list. Returns
    (per_leg_verdicts, correlation_verdict, final_verdict) — the shape
    engine/combine.py consumes to build the actual slip."""
    context = context or {}
    per_leg = [[j(pick, conf, context) for j in PER_LEG_JUDGES]
              for pick, conf in zip(picks, confs)]
    correlation = correlation_judge(picks, confs, context)
    final = final_risk_judge(picks, confs, per_leg, correlation, context)
    return per_leg, correlation, final
