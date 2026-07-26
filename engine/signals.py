"""Which statistic informs which bet, what it means for that bet, and whether we HAVE it.

The research files under research/ already map bet type -> statistics for all 64 sports.
That knowledge was never wired into the engine, so the analysis ran on goals and results
alone while the mapping sat in documents. This module is that mapping made executable, and
— more importantly — made honest: every signal carries its STATUS, so the difference
between "we know this matters" and "we actually use it" is visible instead of implied.

    status = "live"       computed from data we hold, and feeding the model today
             "available"  a free source is verified, but it is not wired in yet
             "missing"    no free source found, or the source is robots-disallowed

`direction` says what the statistic MEANS for that market, which is the part a bare list
of stat names leaves out. "Shots on target" is not simply "relevant to totals" — a high
combined rate pushes the over, and the same number split unevenly pushes a handicap
instead. Without that, a mapping cannot drive an analysis.

The point of the status field is to make the roadmap fall out of the data: anything marked
`available` is work that is already justified, and the gap between live and available is
the honest measure of how far the product is from using what it knows.
"""

# Betwinner market groups, as decoded in engine/bwfeed.py.
MARKETS = {
    1: "1X2",
    101: "moneyline (2-way)",
    8: "double chance",
    2: "handicap",
    2854: "asian handicap",
    17: "total goals/points",
    15: "team 1 total",
    62: "team 2 total",
    109: "set handicap (tennis)",
    7099: "set handicap (table tennis)",
    182: "total sets (tennis)",
    2604: "total sets (table tennis)",
}

FOOTBALL, ICE_HOCKEY, BASKETBALL, TENNIS, TABLE_TENNIS = 1, 2, 3, 4, 10


def S(name, direction, status, source="", tr=""):
    """One signal. `direction` is the engineering statement, `tr` the operator-facing one.

    Both, not one: the module stays readable in the language the rest of the code is
    written in, and the generated method page stays readable in the language the operator
    reads. A single field would have forced one of those to lose.
    """
    return {"signal": name, "direction": direction, "status": status,
            "source": source, "tr": tr or direction}


# --- FOOTBALL ---------------------------------------------------------------
# The only sport with a fitted model today, so it is also the only one with `live` signals.
_FOOTBALL = {
    1: [   # 1X2
        S("elo_rating", "higher rating -> higher win probability for that side",
          "live", "football-data.co.uk, 63409 matches over 39 divisions",
          tr="Takımın gücü. Derecesi yüksek olan tarafın kazanma olasılığı yüksektir; "
             "iki derecenin FARKI maçın tüm tahminlerinin çıkış noktasıdır."),
        S("home_advantage", "home side gains a fitted Elo bonus before the comparison",
          "live", "fitted jointly with the ratings",
          tr="Ev sahipliği. Karşılaştırma yapılmadan önce ev sahibine, veriden ölçülmüş "
             "bir puan eklenir — varsayılan bir sabit değil, fit edilmiş bir değer."),
        S("goal_supremacy", "Elo difference maps to expected goal margin by a per-league fit",
          "live", "least squares per division",
          tr="Beklenen gol farkı. Derece farkı, o LİGE ÖZEL bir fit ile kaç gollük bir "
             "üstünlüğe karşılık geldiğine çevrilir; aynı fark her ligde aynı farkı vermez."),
        S("xg / xga", "expected goals separate luck from finishing; corrects a hot streak",
          "available", "understat / fbref — licence and robots need checking first",
          tr="Beklenen gol. Şansı bitiricilikten ayırır ve geçici bir çıkışı düzeltir: "
             "üç maçta beş gol atan takım gerçekten iyi mi, yoksa şanslı mı."),
        S("injuries_suspensions", "a missing key player lowers that side's effective rating",
          "missing", "no free structured feed found for most leagues",
          tr="Sakat ve cezalı oyuncular. Eksik bir kilit oyuncu, o tarafın etkin gücünü "
             "düşürür. Çoğu lig için ücretsiz ve yapılandırılmış bir kaynak bulunamadı."),
        S("rest_days", "short turnaround lowers the affected side",
          "available", "derivable from our own fixture history once it accumulates",
          tr="Dinlenme süresi. İki maç arası kısaysa o taraf düşer. Kendi fikstür "
             "geçmişimiz biriktikçe dışarıdan kaynak gerekmeden hesaplanabilir."),
    ],
    8: [   # double chance
        S("elo_rating", "same direction as 1X2, but the draw is folded IN rather than against",
          "live", "as above",
          tr="1X2 ile aynı yön, tek farkla: beraberlik bahsin ALEYHİNE değil LEHİNE "
             "sayılır. 'Kaybetmez' bahsi tam olarak budur."),
        S("draw_propensity", "leagues differ sharply and it is fitted per division; a "
                             "high-draw league makes 'does not lose' cheaper in real terms",
          "live", "observed draw rate 21.1%-32.8% across divisions",
          tr="Ligin beraberlik eğilimi. Ligler arasında keskin fark var (ölçülen aralık "
             "%21.1–%32.8) ve her lig için ayrı fit edilir. Beraberliği bol bir ligde "
             "'kaybetmez' bahsi gerçekte daha ucuzdur."),
    ],
    2: [   # handicap
        S("goal_supremacy", "the fitted expected margin IS the handicap's centre",
          "live", "per-division fit",
          tr="Handikabın merkezi doğrudan beklenen gol farkıdır. Çizgi bu merkezden ne "
             "kadar uzaksa bahis o kadar güvenlidir."),
        S("scoreline_distribution", "the spread around that margin decides which line is safe",
          "live", "Poisson pair with a fitted draw correction",
          tr="Skor dağılımı. Ortalama fark tek başına yetmez; o ortalamanın etrafındaki "
             "SAÇILIM hangi handikap çizgisinin güvenli olduğunu belirler. İki Poisson "
             "artı fit edilmiş beraberlik düzeltmesiyle hesaplanır."),
        S("clean_sheet_rate", "a side that concedes rarely narrows the loss tail",
          "available", "computable from the same CSVs, not yet extracted",
          tr="Gol yememe oranı. Az gol yiyen takımın ağır yenilgi ihtimali daralır, bu da "
             "artı handikabı güvenli kılan şeydir. Aynı CSV'lerden hesaplanabilir."),
    ],
    17: [  # totals
        S("league_mean_goals", "the league's own scoring level sets the baseline",
          "live", "fitted per division, 2.37-3.18 goals",
          tr="Ligin gol ortalaması. Alt/üst bahsinin çıkış noktası; ölçülen aralık maç "
             "başına 2.37 ile 3.18 gol arasında değişiyor."),
        S("goal_supremacy", "a lopsided match raises the total; an even one lowers it",
          "live", "per-division fit",
          tr="Beklenen gol farkı, totale de girer: tek taraflı bir maçta toplam gol "
             "yükselir, denk bir maçta düşer. Aynı ortalamayı paylaşan iki maçın alt/üst "
             "olasılıkları bu yüzden aynı değildir."),
        S("shots_on_target", "combined rate leads goals and is more stable game to game",
          "available", "already in the main-division CSVs (HST/AST), not yet used",
          tr="İsabetli şut. İki takımın toplamı golün ÖNCÜ göstergesidir ve maçtan maça "
             "golden daha istikrarlıdır. Veri elimizdeki CSV'lerde zaten var, kullanılmıyor."),
        S("both_teams_scoring_rate", "drives the low end of the totals ladder",
          "available", "computable from the CSVs",
          tr="Karşılıklı gol oranı. Totaller merdiveninin alt ucunu — '0.5 üst', '1.5 üst' "
             "gibi en güvenli basamakları — belirleyen şey budur."),
    ],
    15: [  # team totals
        S("team_attack_strength", "that side's own scoring rate against this opposition",
          "live", "the Poisson mean for that side",
          tr="Takımın hücum gücü: bu rakibe karşı beklenen gol sayısı."),
        S("opponent_defence", "the other side's concession rate scales it",
          "live", "same",
          tr="Rakibin savunması. Hücum gücünü ölçekler: aynı hücum, zayıf savunmaya karşı "
             "daha çok gol demektir."),
    ],
}

# --- TABLE TENNIS -----------------------------------------------------------
# These were all marked `available` when this registry was written, and stayed that way
# after the Setka model was fitted and wired — so the generated method page reported a
# modelled sport as having zero live signals. Corrected here rather than on the page: the
# registry is the claim, and a page that disagreed with it would just be hiding the drift.
_TABLE_TENNIS = {
    1: [
        S("rating_sc", "the circuit's own player rating; higher rating -> higher win probability",
          "live", "Setka API /Players/{lang}/rating; fitted on 7,726 matches",
          tr="Turnuvanın kendi oyuncu derecesi. Yüksek derece, yüksek kazanma olasılığı — "
             "ama masa tenisinde MAÇ kazananı zayıf bir tahmindir; asıl güç set "
             "handikabındadır."),
        S("career_win_rate", "sanity check on the rating and a prior for thin profiles",
          "live", "totalMatches gates the index: under 30 matches a rating is provisional "
                  "and is excluded rather than paired against an established one",
          tr="Kariyer galibiyet oranı. Derecenin sağlamasını yapar ve az maçı olan "
             "oyuncular için başlangıç tahmini verir."),
        S("recent_form", "these circuits play many matches a day; short-window form matters",
          "available", "derivable once the results collector has accumulated enough",
          tr="Yakın form. Bu turnuvalarda günde çok maç oynanır, bu yüzden kısa pencereli "
             "form gerçekten fark eder."),
        S("session_fatigue", "players contest several matches per session; late-session "
                             "matches favour the fresher player",
          "available", "computable from match start times we already collect",
          tr="Seans yorgunluğu. Oyuncular aynı seansta üst üste maç yapar; seansın "
             "sonundaki maçlarda dinç olan avantajlıdır. Zaten topladığımız maç saatlerinden "
             "hesaplanabilir."),
    ],
    7099: [
        S("rating_gap", "a wide gap raises the chance of a straight-sets win, which is what "
                        "decides whether +1.5 or +2.5 sets is the safe rung",
          "live", "buckets the measured set distribution; gaps beyond the fitted range "
                  "are refused rather than extrapolated",
          tr="Derece farkı. Fark açıldıkça setleri kaptırmadan kazanma ihtimali artar; "
             "güvenli basamağın +1.5 mi yoksa +2.5 set mi olduğuna bu karar verir."),
        S("set_score_distribution", "the 3-0/3-1/3-2 split IS the set-handicap market",
          "live", "measured per rating-gap bucket, not derived",
          tr="Set skoru dağılımı. 3-0 / 3-1 / 3-2 oranlarının kendisi set handikabı "
             "piyasasıdır — türetilmiş değil, ÖLÇÜLMÜŞ bir dağılım."),
    ],
}

_TENNIS = {
    1: [
        S("elo_by_surface", "surface-specific rating; a clay rating misprices a hard court",
          "missing", "Sackmann's archive is CC BY-NC-SA — non-commercial only",
          tr="Zemine özel derece. Toprak kortta ölçülmüş bir derece, sert kortu yanlış "
             "fiyatlar. Kaynak lisansı ticari olmayan kullanımla sınırlı."),
        S("serve_hold_rate", "the base rate almost everything in tennis derives from",
          "missing", "same licence constraint",
          tr="Servis koruma oranı. Teniste neredeyse her şey bundan türer; aynı lisans "
             "kısıtı nedeniyle elimizde yok."),
    ],
}

_BY_SPORT = {
    FOOTBALL: _FOOTBALL,
    TABLE_TENNIS: _TABLE_TENNIS,
    TENNIS: _TENNIS,
}


def for_market(sport_id, group):
    """Signals that inform one market, most-wired first."""
    return sorted(_BY_SPORT.get(sport_id, {}).get(group, []),
                  key=lambda s: {"live": 0, "available": 1, "missing": 2}[s["status"]])


def coverage(sport_id=None):
    """How much of the identified signal set the analysis actually uses.

    This is the number that says how far the product is from its own research, and it is
    deliberately computed rather than asserted.
    """
    out = {}
    sports = [sport_id] if sport_id else list(_BY_SPORT)
    for sid in sports:
        counts = {"live": 0, "available": 0, "missing": 0}
        for group, sigs in _BY_SPORT.get(sid, {}).items():
            for s in sigs:
                counts[s["status"]] += 1
        total = sum(counts.values())
        out[sid] = {**counts, "total": total,
                    "live_pct": round(100.0 * counts["live"] / total, 1) if total else 0.0}
    return out
