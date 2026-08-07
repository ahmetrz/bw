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

_BASKETBALL = {
    1: [   # match winner
        S("elo_rating", "higher rating -> higher win probability; the rating DIFFERENCE is "
                        "what every other basketball number here is built on",
          "live", "api-live.euroleague.net, 8,959 EuroLeague + EuroCup games over 19 seasons",
          tr="Takımın gücü. İki derecenin FARKI, basketboldaki her tahminin çıkış noktası."),
        S("home_advantage", "worth a measured 5.5 points, and zero on a neutral court",
          "live", "measured on non-neutral games only",
          tr="Ev sahipliği. Ölçülen değeri 5.5 SAYI — varsayım değil, veriden. Tarafsız "
             "sahada oynanan maçlarda sıfır alınır; yoksa nötr sahadaki bir final tüm ev "
             "çizgilerini aşağı çekerdi."),
        S("club_identity_by_code", "European clubs rename after their sponsor, so a rating "
                                   "keyed by name splits one club's history into fragments",
          "live", "78 of 167 club codes carry more than one name",
          tr="Kulüp kimliği. Avrupa kulüpleri sponsoruna göre ad değiştirir. Derece "
             "sponsor adına göre tutulunca 167 kulüp 343 parçaya bölünmüştü ve her parça "
             "tarihin yalnızca bir kesitini taşıyordu; kod bazlı derece bunu birleştirdi."),
    ],
    2: [   # handicap — where the basketball ladder actually works
        S("margin_distribution", "the margin is close to NORMAL, so P(covers +12.5) is one "
                                 "CDF rather than a sum over a scoreline matrix",
          "live", "residual sd 12.6 points, fitted on 4,039 recent games",
          tr="Fark dağılımı. Basketbolda fark normale yakın, ölçülen sapma 12.6 sayı — bu "
             "yüzden '+12.5 tutar mı' sorusu tek bir hesapla cevaplanıyor. Futbolda aynı "
             "soru için skor matrisi gerekiyor."),
        S("overtime_rate", "the book settles full-game basketball INCLUDING overtime, so "
                           "the fit uses FINAL margins",
          "live", "4.7% of games went to overtime",
          tr="Uzatma oranı (%4.7). Kitap basketbolu uzatmalar DAHİL sonuçlandırdığı için "
             "model normal süreye değil final farkına fit edildi. Normal süreye fit etmek, "
             "handikabın karara bağlandığı yakın maçları tam da yanlış fiyatlamak olurdu."),
        S("cover_rate_calibration", "the predicted cover rate is checked against the "
                                    "observed one, line by line",
          "live", "worst gap 0.030 at +2.5 and at or under 0.011 from +6.5 upward",
          tr="Kapanma oranı kalibrasyonu. Modelin iddiası gerçekleşenle çizgi çizgi "
             "karşılaştırılıyor. İlk fitte model +12.5 için %90.4 diyordu, gerçek %74.9'du "
             "— güven tabanı bunu ASLA yakalayamazdı, çünkü taban modele güvenir."),
        S("pace_and_efficiency", "possessions and points per possession sharpen the margin "
                                 "beyond what one rating carries",
          "available", "the EuroLeague boxscore API exposes both; not yet extracted",
          tr="Tempo ve verimlilik. Hücum başına sayı ve maç temposu, tek bir derecenin "
             "taşıyamadığı ayrıntıyı ekler. EuroLeague kutu skoru API'sinde mevcut, henüz "
             "çıkarılmadı."),
        S("injuries", "short rotations make one absence move a basketball line more than "
                      "in any other team sport",
          "missing", "no free structured feed for European leagues",
          tr="Sakatlıklar. Rotasyon dar olduğu için eksik bir oyuncu çizgiyi diğer takım "
             "sporlarından daha çok oynatır. Avrupa ligleri için ücretsiz ve yapılandırılmış "
             "bir kaynak bulunamadı."),
    ],
    17: [  # totals
        S("league_mean_total", "the base rate the totals ladder starts from",
          "live", "163.4 points, sd 18.4",
          tr="Ortalama toplam sayı: 163.4, sapma 18.4. Alt/üst merdiveninin çıkış noktası."),
        S("rating_gap_effect", "a mismatch moves the expected total; an even game and a "
                               "blowout do not score alike",
          "live", "fitted against the absolute rating gap",
          tr="Derece farkının totale etkisi. Denk bir maçla tek taraflı bir maçın toplam "
             "sayısı aynı değildir; fark beklenen totali kaydırır."),
    ],
}


# These were marked `missing` for a Sackmann-derived, surface-aware model that was
# considered and never built — the licence blocked it (Sackmann's archive is CC BY-NC-SA)
# and stayed that way even after tennis was actually wired in through a completely
# different route: engine/model_generic.py, on TML + tennisexplorer + the live watcher
# (docs/TENNIS_MODELS.md, docs/DECISIONS/0007). Exactly the drift the table tennis
# section above already had once — a modelled sport reporting zero live signals because
# the registry described a plan instead of the pipeline that shipped. Corrected here,
# against what tennis's model actually is today, not the surface-elo idea it replaced.
_TENNIS = {
    1: [
        S("generic_rating", "counted rating from results alone; higher rating -> higher "
                            "win probability for that side",
          "live", "engine/model_generic.py, fitted on TML + tennisexplorer + the live "
                  "watcher (38,749 matches); held-out calibration gap 0.023",
          tr="Sayılmış derece. Elo gibi fit edilmiş değil, gerçekleşmiş sonuçlardan "
             "SAYILARAK kurulur. Yüksek dereceli tarafın kazanma olasılığı yüksektir."),
        S("bo3_bo5_pool_separation", "a Grand Slam men's draw plays best-of-five and every "
                                     "other tour match best-of-three; pooled they are two "
                                     "different games on one scale",
          "live", "engine/model_generic.py pool key, read from TML's best_of column and "
                  "from the live score for watcher-collected matches",
          tr="Bo3/Bo5 ayrımı. Grand Slam erkekler tekleri beş set, geri kalan her şey üç "
             "set üzerinden oynanır; ayrılmazsa aynı skalada iki farklı oyun karışır."),
    ],
    109: [   # set handicap
        S("rating_gap", "a wide gap raises the chance of a straight-sets win, which is "
                        "what decides whether +1.5 or +2.5 sets is the safe rung",
          "live", "buckets the counted set-margin distribution by rating gap; gaps beyond "
                  "the fitted range are refused rather than extrapolated",
          tr="Derece farkı. Fark açıldıkça set kaybetmeden kazanma ihtimali artar; güvenli "
             "basamağın +1.5 mi yoksa +2.5 set mi olduğuna bu karar verir."),
    ],
    182: [   # total sets
        S("set_total_distribution", "the counted two-set/three-set split by rating gap "
                                    "sets the totals ladder",
          "live", "the same counted distribution as the handicap, read for the total "
                  "instead of the margin",
          tr="Set toplamı dağılımı. Aynı ölçülmüş dağılım, bu kez maçın kaç sette "
             "bittiğini okumak için kullanılır."),
    ],
}

_BY_SPORT = {
    FOOTBALL: _FOOTBALL,
    BASKETBALL: _BASKETBALL,
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
