"""Turkish labels for market types and selections.

The feed publishes numeric ids and this project turns them into terse English tokens
("H1 1.5", "1X", "ML2") that read as internal notation. The slip is used on a phone, at
speed, by someone deciding whether to place a bet — so it shows Turkish, and it says what
the selection MEANS rather than what the feed called it.

Only labels whose meaning was established from a real payload appear here. Anything else
falls through to its raw token, because a confident-looking Turkish label on a market we
have not decoded would be worse than the raw one: it would read as understood.
"""

MARKET_TYPES = {
    "moneyline": "Maç Sonucu (1X2)",
    "moneyline2way": "Maç Sonucu (çift seçenek)",
    "doubleChance": "Çifte Şans",
    "spreads": "Handikap",
    "totals": "Toplam Alt/Üst",
    "teamTotal": "Takım Toplamı",
    "setHandicap": "Set Handikapı",
    "totalSets": "Toplam Set",
    "correctScore": "Skor Tahmini",
    "other": "Diğer",
}

# Settlement scope, in the words a bettor needs to see on the slip.
SCOPES = {
    "regulation": "normal süre",
    "includes_ot": "uzatmalar dahil",
    "match": "maçın tamamı",
    "unknown": "kapsamı teyit edilmedi",
}

# Exact selection tokens produced by engine/bwfeed.OUTCOME_LABELS.
_EXACT = {
    "1": "1 (ev sahibi kazanır)",
    "X": "X (beraberlik)",
    "2": "2 (deplasman kazanır)",
    "1X": "1 veya X — ev sahibi kaybetmez",
    "X2": "X veya 2 — deplasman kaybetmez",
    "12": "Beraberlik olmaz",
    "ML1": "1 kazanır (uzatmalar dahil)",
    "ML2": "2 kazanır (uzatmalar dahil)",
}

# Tokens that carry a line value after them.
_PREFIXED = [
    ("sets over ", "{v} Set Üst"),
    ("sets under ", "{v} Set Alt"),
    ("T1 over ", "1. taraf {v} Üst"),
    ("T1 under ", "1. taraf {v} Alt"),
    ("T2 over ", "2. taraf {v} Üst"),
    ("T2 under ", "2. taraf {v} Alt"),
    ("over ", "{v} Üst"),
    ("under ", "{v} Alt"),
    ("SH1 ", "1. taraf {v} set handikap"),
    ("SH2 ", "2. taraf {v} set handikap"),
    ("H1 ", "1. taraf {v} handikap"),
    ("H2 ", "2. taraf {v} handikap"),
]


def market_type(mtype):
    return MARKET_TYPES.get(mtype, mtype)


def scope(name):
    return SCOPES.get(name, name or "bilinmiyor")


def selection(label):
    """Turkish reading of a selection token, or the token itself if we cannot vouch for it.

    Sub-game markets arrive tagged like "[1st half] over 1.5"; the tag is preserved and
    only the market part is translated, since the tag is the book's own wording for which
    period the bet covers and inventing a Turkish version of it could misstate the period.
    """
    if label is None:
        return ""
    text = str(label)
    tag = ""
    if text.startswith("["):
        end = text.find("]")
        if end != -1:
            tag, text = text[: end + 1] + " ", text[end + 1:].strip()

    if text in _EXACT:
        return tag + _EXACT[text]
    for prefix, template in _PREFIXED:
        if text.startswith(prefix):
            return tag + template.format(v=text[len(prefix):].strip())
    return tag + text


# Turkish settlement text, keyed by engine.settlement.describe()'s `key` — "<sport>.<group>"
# for a rule that names a specific market, "<sport>.*" for the sport's general rule. Kept
# here rather than in settlement.py so that module stays one language, and looked up by key
# rather than by matching the English text, which would break the moment it is reworded.
SETTLEMENT = {
    "1.*": "90 dakika + uzatma dakikaları. Uzatmalar ve penaltılar SAYILMAZ.",
    "1.1": "Maç sonucu 90. dakikada belirlenir. Eleme maçında tur devam etse bile bu bahis 90'da sonuçlanır.",
    "1.8": "Çifte şans 90. dakikada sonuçlanır. Takım uzatmalarda kaybetse bile 'kaybetmez' bahsi KAZANIR.",
    "1.2": "Handikap 90. dakikada sonuçlanır, uzatmalar hariç.",
    "1.17": "Toplam gol 90. dakikada sonuçlanır. Penaltı atışlarındaki goller asla sayılmaz.",

    "3.*": "Maç sonucu, handikap ve toplam sayı UZATMALARI İÇERİR; çeyrek/devre bahisleri içermez.",
    "3.101": "İki seçenekli maç sonucu. Uzatmalar dahildir, bu yüzden beraberlik yoktur.",
    "3.2": "Maçın tamamı üzerinden handikap, uzatmalar dahil.",
    "3.17": "Maçın tamamı üzerinden toplam sayı, uzatmalar dahil.",

    "4.*": "Maçın tamamı üzerinden sonuçlanır. Maçı bırakma (retirement) durumunda set handikabı, toplam ve skor bahisleri — sonucu belli olmamışsa — İPTAL edilir.",
    "4.1": "Maç kazananı. İki seçenek — teniste beraberlik yoktur.",
    "4.109": "SET handikabı. 3 setlik maçta +1.5 set yalnızca 0-2 yenilgide kaybeder; yani 'en az bir set alır' bahsidir.",
    "4.2": "OYUN (game) handikabı, set değil. Çizgi oyun sayısını sayar.",
    "4.17": "Toplam OYUN sayısı, set değil.",
    "4.182": "Toplam SET sayısı.",

    "2.*": "DİKKAT: bu platformda toplam ve handikap bahisleri, etiketinde 'uzatma dahil' yazmıyorsa çoğunlukla NORMAL SÜREYE göre sonuçlanır. Aynı 'Üst 5.5' iki farklı bahis olabilir.",
    "2.1": "Üç seçenekli sonuç, NORMAL SÜRE (60 dakika) sonunda belirlenir. Beraberlik gerçek bir sonuçtur.",
    "2.101": "İki seçenekli maç sonucu, UZATMA ve penaltı atışları DAHİL. Beraberlik yoktur. Üç seçenekli pazarla aynı maç, farklı bahis.",
    "2.8": "NORMAL SÜRE üzerinden çifte şans — 'kaybetmez', 60 dakika sonunda kaybetmemek demektir.",
    "2.2": "Handikap. Betwinner'da kapsamı TEYİT EDİLMEDİ: bu platform hokey handikaplarını sıklıkla normal süreye göre sonuçlandırır.",
    "2.17": "Toplam gol. Betwinner'da kapsamı TEYİT EDİLMEDİ: uzatmaları hariç tutuyor olabilir.",

    "10.*": "Maçın tamamı üzerinden sonuçlanır. Format (5 mi 7 set mi) HER MAÇ İÇİN ayrı okunmalı — play-off'larda 7 sete çıkar. Maçı bırakma, sonucu belli olmayan bahisleri iptal eder.",
    "10.1": "Maç kazananı. İki seçenek — beraberlik yoktur.",
    "10.7099": "SET handikabı. 5 setlik maçta 'en az bir set alır' basamağı +2.5'tir; +1.5 ise 'en az iki set alır' demektir.",
    "10.2": "SAYI (point) handikabı, set değil. Çizgi sayıları sayar.",
    "10.17": "Toplam SAYI, set değil.",
    "10.2604": "Toplam SET sayısı.",

    "unknown": "Bu spor için sonuçlanma kuralları henüz belgelenmedi; temkinli yaklaşın.",
}


def settlement(spec):
    """Turkish settlement text for a dict from engine.settlement.describe().

    Falls back to the sport's general rule, then to the English text, so an undocumented
    market shows something true rather than an empty line.
    """
    if not spec:
        return ""
    key = spec.get("key") or "unknown"
    if key in SETTLEMENT:
        return SETTLEMENT[key]
    sport_general = key.split(".", 1)[0] + ".*"
    return SETTLEMENT.get(sport_general) or spec.get("detail", "")


def ladder_note(row):
    """One line explaining why this selection, not the more obvious one.

    Only meaningful on a laddered pick. The point of the ladder is that it deliberately
    does NOT take the outright win, so the slip should say so rather than leave the reader
    wondering why a safer market was chosen.
    """
    rung = row.get("ladder_rung")
    if not rung:
        return None
    depth = row.get("ladder_depth")
    available = row.get("ladder_available")
    if depth is None or available is None:
        return "En garanti seçenek"
    return (f"Aynı yöndeki en garanti {depth + 1}. basamak "
            f"({available} basamak içinden, oran {'≥'} 1.10 filtresiyle)")
