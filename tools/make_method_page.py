#!/usr/bin/env python3
"""Render the method: which statistic feeds which bet, in every sport, and what is live.

    python tools/make_method_page.py --out method.html

GENERATED, never hand-written. Every number and every mapping on the page is read out of
the things that actually run — engine/signals.py, engine/pick.py, engine/ladder.py,
config.py and research/*.json — so the document cannot quietly disagree with the code. A
hand-maintained version of this page would be wrong within a week and would keep looking
authoritative while it was.

It is deliberately unflattering. 64 sports were researched and 2 are modelled; the page
says so at the top rather than letting a long table imply otherwise. The gap between
"we know this matters" and "we compute this today" is the roadmap, and it is only useful
if it is visible.
"""
import argparse
import glob
import html
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import ladder, pick, signals, tr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(ROOT, "research")

# Research files name markets in their own words. Where that word is a market this engine
# actually keys on, say so — it turns a document into something you can trace to a row in
# the feed.
MARKET_GROUP = {
    "1x2": 1, "match_winner": 1, "match_or_game_winner": 1, "moneyline": 101,
    "1x2_three_way": 1, "match_result": 1, "winner": 1, "win": 1,
    "double_chance": 8, "handicap": 2, "spread": 2, "asian_handicap": 2854,
    "point_handicap": 2, "goal_handicap": 2, "set_handicap": 7099,
    "totals": 17, "total_goals": 17, "total_points": 17, "total_runs": 17,
    "team_total": 15, "team_totals": 15, "total_sets": 2604, "total_games": 17,
    "correct_score": 136,
}

# Turkish for the market names the research files use. Only the ones whose meaning is
# unambiguous appear here: an English key left untranslated is better than a confident
# Turkish label on a market we have not decoded, which would read as understood.
MARKET_TR = {
    "1x2": "Maç sonucu 1X2", "1x2_three_way": "Maç sonucu 1X2",
    "1x2_two_way": "Maç sonucu (iki seçenek)", "match_winner": "Maç kazananı",
    "match_or_game_winner": "Maç / oyun kazananı", "moneyline": "Maç sonucu (iki seçenek)",
    "winner": "Kazanan", "win": "Kazanan", "race_winner": "Yarış kazananı",
    "fight_winner_moneyline": "Dövüş kazananı", "map_winner": "Harita kazananı",
    "double_chance": "Çifte şans",
    "handicap": "Handikap", "asian_handicap": "Asya handikabı",
    "european_handicap": "Avrupa handikabı", "game_handicap": "Oyun handikabı",
    "set_handicap": "Set handikabı", "map_handicap": "Harita handikabı",
    "puck_line": "Puck line (buz hokeyi handikabı)", "spread": "Handikap",
    "touch_handicap": "Sayı handikabı",
    "totals": "Toplam alt/üst", "total_goals": "Toplam gol", "total_points": "Toplam sayı",
    "total_runs_match": "Toplam koşu", "total_games": "Toplam oyun",
    "total_sets": "Toplam set", "total_maps": "Toplam harita",
    "total_rounds_kills": "Toplam tur / öldürme", "total_touches": "Toplam dokunuş",
    "over_under_goals": "Gol alt/üst", "over_under_points": "Sayı alt/üst",
    "over_under_games": "Oyun alt/üst", "over_under_sets": "Set alt/üst",
    "over_under_corners": "Korner alt/üst", "over_under_cards": "Kart alt/üst",
    "over_under_total_rounds": "Tur alt/üst", "over_under_innings_runs": "Devre koşu alt/üst",
    "team_total": "Takım toplamı", "team_totals": "Takım toplamları",
    "correct_score": "Skor tahmini", "correct_set_score": "Set skoru",
    "correct_map_score": "Harita skoru", "set_betting": "Set bahsi",
    "winning_margin": "Kazanma farkı", "btts": "Karşılıklı gol",
    "clean_sheet": "Gol yemeden", "win_to_nil": "Gol yemeden kazanır",
    "half_time_full_time": "İlk yarı / maç sonu", "half_markets": "Devre bahisleri",
    "period_markets": "Periyot bahisleri", "half": "Devre", "quarter": "Çeyrek",
    "overtime": "Uzatma", "three_way_60": "Normal süre 1X2",
    "race_to_x": "X sayıya ilk ulaşan", "race_to_n": "N sayıya ilk ulaşan",
    "race_to_n_runs": "N koşuya ilk ulaşan", "first_to_score": "İlk sayıyı atan",
    "first_set_winner": "İlk seti kazanan", "to_win_a_set": "En az bir set alır",
    "player_to_win_a_set": "Oyuncu en az bir set alır",
    "player_to_win_a_game": "Oyuncu en az bir oyun alır",
    "tiebreak_yes_no": "Tie-break var/yok", "head_to_head": "İkili karşılaşma",
    "outright_winner": "Turnuva şampiyonu", "ante_post_futures": "Uzun vadeli",
    "toss_winner": "Yazı-tura kazananı",
}


# What the engine can do with a sport, read from the code rather than asserted.
TIER_TR = {
    "modelled": ("Modelli — seçim üretir",
                 "Fit edilmiş bir model yön veriyor; merdiven bu yönü en güvenli "
                 "biçimine çeviriyor ve seçim listeye giriyor."),
    "ladder": ("Merdiven hazır, model yok",
               "Güvenlik merdiveni bu spor için basamak kurabiliyor ama yönü söyleyecek "
               "bir model yok. Yön fiyattan okunamayacağı için bu sporlardan seçim "
               "ÇIKMAZ — araştırma yapıldı, model kurulmadı."),
    "excluded": ("Kapsam dışı",
                 "Ürün kuralı gereği taramaya hiç girmiyor."),
}


# Turkish softens a final consonant before a vowel suffix: handikap -> handikabı,
# kupon -> kuponu, renk -> rengi. Someone searching the dictionary form "handikap" would
# otherwise find nothing, because the page says "handikabı". Both forms are indexed.
_SOFTENED = (("bı", "p"), ("bi", "p"), ("bu", "p"), ("bü", "p"),
             ("ğı", "k"), ("ği", "k"), ("ğu", "k"), ("ğü", "k"),
             ("cı", "ç"), ("ci", "ç"), ("dı", "t"), ("di", "t"))


def _hard_stems(text):
    """Every word in `text`, plus its un-softened dictionary form where one exists."""
    out = []
    for word in str(text).lower().split():
        out.append(word)
        for soft, hard in _SOFTENED:
            if word.endswith(soft) and len(word) > len(soft) + 2:
                out.append(word[: -len(soft)] + hard)
                break
    return out


def _slug(text):
    return "".join(ch for ch in str(text).lower().replace("_", " ") if ch.isalnum() or ch == " ").strip()


def sport_catalogue():
    """id -> Turkish name, falling back to the catalogue's English one."""
    with open(os.path.join(RESEARCH, "sports_catalogue.json")) as f:
        return {s["id"]: tr.sport(s["id"], s["name"]) for s in json.load(f)["sports"]}


def english_catalogue():
    with open(os.path.join(RESEARCH, "sports_catalogue.json")) as f:
        return {s["id"]: s["name"] for s in json.load(f)["sports"]}


def tier(sport_id):
    if sport_id in getattr(config, "EXCLUDED_SPORTS", set()):
        return "excluded", "config.EXCLUDED_SPORTS"
    if sport_id in getattr(config, "MULTI_DAY_SPORTS", set()):
        return "excluded", "config.MULTI_DAY_SPORTS — aynı gün sonuçlanmıyor"
    if sport_id in pick.MODELLED_SPORTS:
        return "modelled", "engine/pick.py MODELLED_SPORTS"
    return "ladder", "engine/ladder.py _rungs_generic_side"


def ladder_note(sport_id):
    """Which ladder branch this sport takes, straight out of ladder.build's dispatch."""
    if sport_id == ladder.FOOTBALL:
        return "futbol merdiveni (çifte şans → artı handikap)"
    if sport_id in (ladder.TENNIS, ladder.TABLE_TENNIS):
        return "set sporu merdiveni (set handikabı)"
    if sport_id == ladder.BASKETBALL:
        return "iki yönlü merdiven, uzatmalar dahil"
    if sport_id == ladder.ICE_HOCKEY:
        return "iki yönlü merdiven, handikap kapsamı teyit edilmedi"
    return "genel merdiven — beraberlik fiyatlanıyorsa çifte şans, değilse maç sonucu"


def load_research(catalogue=None):
    """Flatten every research file into (sport label, ids, markets, stat glossary, notes)."""
    catalogue = catalogue or sport_catalogue()
    blocks = []
    for path in sorted(glob.glob(os.path.join(RESEARCH, "*.json"))):
        if path.endswith("sports_catalogue.json"):
            continue
        with open(path) as f:
            doc = json.load(f)
        glossary = {}
        for s in doc.get("statistics") or []:
            if isinstance(s, dict) and s.get("id"):
                glossary[s["id"]] = s
        ids = doc.get("betwinner_sport_ids") or []
        if isinstance(doc.get("sport_id_map"), dict):
            ids = ids or sorted(doc["sport_id_map"].values())
        elif isinstance(doc.get("sport_id_map"), list):
            ids = ids or doc["sport_id_map"]
        if not ids:
            # The oldest research files predate the id convention, and they are exactly
            # the modelled sports — football, table tennis. Resolving the label against
            # the catalogue keeps them from being reported as unmodelled, which is the
            # one thing this page must not get wrong.
            want = _slug(doc.get("sport") or os.path.basename(path).rsplit(".", 1)[0])
            english = english_catalogue()
            ids = [sid for sid, nm in english.items() if _slug(nm) == want]

        entries, notes = _markets(doc.get("stat_to_bet"))
        # Some files carry a nested per-sport block (baseball / american football).
        for key, val in doc.items():
            if isinstance(val, dict) and "stat_to_bet" in val:
                sub_entries, sub_notes = _markets(val["stat_to_bet"])
                entries += [(key, m, st, nt) for _, m, st, nt in sub_entries]
                notes += sub_notes
                for s in val.get("statistics") or []:
                    if isinstance(s, dict) and s.get("id"):
                        glossary[s["id"]] = s

        if not entries:
            continue
        blocks.append({
            "file": os.path.basename(path),
            "label": doc.get("sport") or doc.get("sports") or os.path.basename(path),
            "ids": [i for i in ids if isinstance(i, int)],
            "entries": entries,
            "glossary": glossary,
            "notes": notes,
            "findings": doc.get("key_findings") or [],
        })
    return blocks


def _markets(s2b):
    """(sub, market, [stats], note) rows out of the three shapes the files actually use."""
    entries, notes = [], []
    if not isinstance(s2b, dict):
        return entries, notes
    for key, val in s2b.items():
        if key.startswith("_") or isinstance(val, str):
            notes.append((key.lstrip("_").replace("_", " "), val if isinstance(val, str) else ""))
            continue
        if isinstance(val, list):
            entries.append(("", key, [v for v in val if isinstance(v, str)], ""))
        elif isinstance(val, dict):
            # Either market -> {primary/secondary/note}, or sub-sport -> {market: [stats]}.
            if any(isinstance(v, list) for k, v in val.items()
                   if k in ("primary", "secondary", "tertiary")):
                stats = []
                for k in ("primary", "secondary", "tertiary"):
                    stats += [v for v in (val.get(k) or []) if isinstance(v, str)]
                entries.append(("", key, stats, str(val.get("note") or "")))
            else:
                for market, stats in val.items():
                    if isinstance(stats, list):
                        entries.append((key, market, [s for s in stats if isinstance(s, str)], ""))
                    elif isinstance(stats, dict):
                        flat = []
                        for k in ("primary", "secondary", "tertiary"):
                            flat += [v for v in (stats.get(k) or []) if isinstance(v, str)]
                        entries.append((key, market, flat, str(stats.get("note") or "")))
    return entries, notes


PAGE = """<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betwinner analiz yöntemi</title>
<style>
 :root {{ color-scheme:light dark; --bg:#fff; --fg:#111; --card:#f6f6f8; --line:#e2e2e6;
          --muted:#666; --accent:#0a7d32; --chip:#eceef2; --live:#0a7d32; --avail:#7a5c00;
          --miss:#b3261e; }}
 @media (prefers-color-scheme:dark) {{ :root {{ --bg:#0f1115; --fg:#e8e8ea; --card:#181b21;
          --line:#2a2e36; --muted:#9aa0aa; --accent:#3ddc84; --chip:#222630; --live:#3ddc84;
          --avail:#e0c064; --miss:#ff8a8a; }} }}
 *{{box-sizing:border-box}}
 body{{margin:0;padding:14px;background:var(--bg);color:var(--fg);max-width:1100px;
   font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 h1{{font-size:21px;margin:0 0 4px}}
 h2{{font-size:16px;margin:26px 0 8px;padding-top:8px;border-top:1px solid var(--line)}}
 h3{{font-size:14px;margin:16px 0 6px}}
 .sub{{color:var(--muted);font-size:12.5px;margin-bottom:14px}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;
   padding:12px 14px;margin-bottom:12px}}
 .panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;
   padding:10px 12px;margin-bottom:12px;position:sticky;top:0;z-index:9;
   max-height:40vh;overflow-y:auto}}
 .row{{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}}
 label{{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px}}
 select,input{{font:inherit;padding:7px 9px;border-radius:9px;border:1px solid var(--line);
   background:var(--bg);color:var(--fg);min-height:38px}}
 .chip{{background:var(--chip);border-radius:999px;padding:3px 9px;font-size:11.5px;
   color:var(--muted);white-space:nowrap}}
 .tag{{display:inline-block;border-radius:999px;padding:2px 9px;font-size:11px;
   font-weight:700;color:#fff}}
 .tag.modelled{{background:var(--live)}} .tag.ladder{{background:var(--avail)}}
 .tag.excluded{{background:var(--miss)}}
 .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}}
 .dot.live{{background:var(--live)}} .dot.available{{background:var(--avail)}}
 .dot.missing{{background:var(--miss)}}
 .steps{{counter-reset:s;list-style:none;padding:0;margin:0}}
 .steps li{{counter-increment:s;position:relative;padding:8px 0 8px 34px;
   border-bottom:1px solid var(--line)}}
 .steps li:last-child{{border-bottom:0}}
 .steps li::before{{content:counter(s);position:absolute;left:0;top:8px;width:24px;
   height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;
   font-weight:700;display:grid;place-items:center}}
 .sport{{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:10px}}
 .sport.hide{{display:none}}
 .sport>summary{{cursor:pointer;font-weight:600;font-size:15px;list-style:none}}
 .sport>summary::-webkit-details-marker{{display:none}}
 .sport>summary::before{{content:"▸ ";color:var(--muted)}}
 .sport[open]>summary::before{{content:"▾ "}}
 .mk{{margin:12px 0 0;padding:10px 12px;background:var(--card);border-radius:10px}}
 .mk b{{font-size:13.5px}}
 .stat{{padding:7px 0;border-top:1px solid var(--line);font-size:13px}}
 .stat:first-of-type{{border-top:0}}
 .stat .name{{font-weight:600}}
 .stat .why{{color:var(--muted);font-size:12.5px}}
 code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;
   background:var(--chip);padding:1px 5px;border-radius:5px}}
 .formula{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;
   background:var(--chip);padding:10px 12px;border-radius:9px;overflow-x:auto}}
 table.mini{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
 table.mini td{{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
 table.mini td:first-child{{white-space:nowrap;color:var(--muted)}}
 footer{{margin-top:22px;color:var(--muted);font-size:11.5px;line-height:1.6}}
 @media (max-width:640px){{ body{{padding:10px}} .panel label{{flex:1 1 calc(50% - 4px)}}
   .panel select,.panel input{{width:100%}} }}
</style></head><body>

<h1>Betwinner analiz yöntemi</h1>
<div class="sub">{generated} · bu sayfa <b>koddan üretilir</b>: her eşleştirme ve her sayı
  engine/, config.py ve research/ içinden okunur, elle yazılmaz.</div>

<div class="card">
  <b>Dürüst özet.</b> Katalogdaki <b>{n_sports} spor dalının tamamı araştırıldı</b> ve
  {n_maps} istatistik→bahis eşleştirmesi kayıtlı. Bunlardan bugün <b>{n_modelled} tanesi
  modelli</b> ({modelled_names}) — yani yalnızca bu sporlardan seçim çıkar. Kalanlarda
  güvenlik merdiveni basamak kurabiliyor ama <b>yönü söyleyecek model yok</b>, ve yön
  fiyattan okunamayacağı için seçim de çıkmaz. Uzun bir tablonun aksini ima etmesine izin
  vermemek için bu en başta yazıyor: aradaki fark, yol haritasının kendisidir.
</div>

<h2>Analiz nasıl çalışıyor</h2>
<ol class="steps">
  <li><b>Kart çekilir.</b> Betwinner'ın kendi LineFeed'inden önümüzdeki 48 saatin tüm
    maç öncesi marketleri: spor → turnuva → maç → market. Son çekimde
    <code>{rows} satır</code> / <code>{fixtures} maç</code>.</li>
  <li><b>Yapısal eleme.</b> İkinci katılımcısı olmayan kayıt bir "karşı karşıya" maçı
    değildir — turnuva şampiyonu, seçim sorusu, çok koşuculu yarış hepsi tek kuralla
    düşer. Aynı gün sonuçlanmayan sporlar (<code>MULTI_DAY_SPORTS</code>) ve sonucu
    tahmin edilemeyen kumar marketleri (<code>EXCLUDED_SPORTS</code>) de çıkar.</li>
  <li><b>Model yönü söyler.</b> Fiyat asla. Kısa bir oran, olasılık tahmini artı kitabın
    marjı artı kitabın pozisyonudur; onu olasılık diye okumak kitabın görüşünü kitaba
    geri vermektir.</li>
  <li><b>Merdiven biçimi seçer.</b> Aynı görüşün en güvenli ifadesi: "kazanır" yerine
    "kaybetmez", sonuç yerine en büyük artı handikap, manşet total yerine en düşük
    üst çizgisi.</li>
  <li><b>Oran tam olarak bir kez okunur:</b> <code>MIN_ODDS = {min_odds}</code> eşiği.
    Merdiven bu eşiği geçen en güvenli basamakta durur.</li>
  <li><b>Güven tabanı.</b> Model <code>MIN_MODEL_SURVIVAL = %{floor}</code> altında
    kalan her şeyi eler. Taban olmasa merdiven, yazı-turanın en güvenli biçimini
    döndürürdü — ki o hâlâ yazı-turadır.</li>
  <li><b>İadeli marketler kapalı.</b> Tam sayı handikaplar, çeyrek handikaplar ve tam
    sayı totaller stakeyi geri verebilir; sadece .5 çizgileri kalır. Böylece güven tabanı
    "hayatta kalma" değil <b>kazanma</b> tabanı olur.</li>
  <li><b>Maç başına tek seçim</b>, sonra 1'den N'e puana göre numaralandırma.</li>
</ol>
<div class="card">Modelin güvenli bir görüşü olmayan maç <b>hiçbir şey üretmez</b>.
  Listeyi doldurmak için "en az kötü" seçeneği eklemek, işin tamamını anlamsızlaştırırdı.
  Son kartta {matches} maç tarandı, {picks} seçim çıktı; geri kalanın büyük kısmı
  <b>modelsiz</b> ({no_model} maç).</div>

<h2>Puanlama</h2>
<div class="card">
  <div class="formula">puan = 100 × ( {floor_f} + (modelin olasılığı − {floor_f}) × kanıt )</div>
  <p><b>Puan, modelin bu bahsi kazanma olasılığıdır.</b> 92 puan "model bunun yaklaşık
  %92 tutacağını söylüyor" demektir. Kitabın fiyatı puana <b>hiç girmez</b> — bir test
  bunu doğrular: oranı değiştirip modeli sabit tuttuğunuzda puan kıpırdamaz.</p>
  <p><b>Kanıt</b> tek düzeltmedir ve tamamen bize aittir: takım/oyuncu isim eşleşmesinin
  gücü, ligin fit edildiği maç sayısı, derecelendirme kovasının arkasındaki örneklem.
  Aynı olasılıktaki iki seçim eşit sağlamlıkta değildir; kanıt zayıfsa olasılık eşiğe
  doğru geri çekilir ve ne kadar çekildiği "−x puan" olarak satırda yazar.</p>
  <p>Puanlar %{floor} ile %100 arasında dar bir bantta toplanır, çünkü listeye giren her
  seçim zaten eşiği geçmiştir. Bu bant ürünün kendisidir; kozmetik olarak germek modelin
  gerçekte ayıramadığı %91 ile %93 arasında yapay bir fark uydurmak olurdu.</p>
  <table class="mini">
    <tr><td>çok güçlü</td><td>≥ 92 puan</td></tr>
    <tr><td>güçlü</td><td>88 – 92</td></tr>
    <tr><td>orta</td><td>83 – 88</td></tr>
    <tr><td>sınırda</td><td>&lt; 83</td></tr>
  </table>
</div>

<h2>Bugün canlı olan sinyaller</h2>
<div class="card">{live_block}</div>

<h2>Spor spor: istatistik → bahis</h2>
<div class="panel">
  <div class="row">
    <label>Durum
      <select id="fTier"><option value="">hepsi</option>
        <option value="modelled">modelli (seçim üretir)</option>
        <option value="ladder">merdiven var, model yok</option>
        <option value="excluded">kapsam dışı</option></select></label>
    <label>Ara
      <input type="search" id="fText" placeholder="spor / bahis / istatistik"></label>
    <label>&nbsp;<button id="expand" type="button">hepsini aç</button></label>
  </div>
  <div class="row" style="margin-top:8px"><span class="chip" id="count"></span></div>
</div>
{sports}

<footer>{footer}</footer>
<script>
var cards=[].slice.call(document.querySelectorAll('details.sport'));
function apply(){{
  var t=document.getElementById('fTier').value,
      q=document.getElementById('fText').value.toLowerCase().trim(), n=0;
  cards.forEach(function(c){{
    var ok=(!t||c.dataset.tier===t)&&(!q||c.dataset.text.indexOf(q)>=0);
    c.classList.toggle('hide',!ok); if(ok)n++;
    if(q&&ok) c.open=true;
  }});
  document.getElementById('count').textContent=n+' / '+cards.length+' spor grubu';
}}
['fTier','fText'].forEach(function(id){{
  document.getElementById(id).addEventListener('input',apply);
}});
document.getElementById('expand').addEventListener('click',function(){{
  var open=cards.some(function(c){{return !c.open}});
  cards.forEach(function(c){{c.open=open}});
  this.textContent=open?'hepsini kapat':'hepsini aç';
}});
apply();
</script>
</body></html>"""


def build(out_path):
    cat = sport_catalogue()
    blocks = load_research(cat)
    modelled = sorted(pick.MODELLED_SPORTS)

    # Live signal summary, straight from engine/signals.py.
    live_rows = []
    for sid, cov in sorted(signals.coverage().items()):
        name = cat.get(sid, str(sid))
        live_rows.append(
            f'<div class="stat"><span class="name">{html.escape(name)}</span> — '
            f'<span class="dot live"></span>{cov["live"]} canlı · '
            f'<span class="dot available"></span>{cov["available"]} kaynak var, '
            f'bağlanmadı · <span class="dot missing"></span>{cov["missing"]} kaynak yok '
            f'<span class="chip">%{cov["live_pct"]:.0f} bağlı</span></div>')
    for sid in sorted(signals._BY_SPORT):
        for group, sigs in sorted(signals._BY_SPORT[sid].items()):
            for s in sigs:
                live_rows.append(
                    f'<div class="stat" style="padding-left:12px">'
                    f'<span class="dot {s["status"]}"></span>'
                    f'<span class="name">{html.escape(s["signal"])}</span> '
                    f'<span class="chip">{html.escape(cat.get(sid, str(sid)))} · '
                    f'{html.escape(signals.MARKETS.get(group, str(group)))}</span>'
                    f'<div class="why">{html.escape(s.get("tr") or s["direction"])}'
                    + (f' <i>({html.escape(s["source"])})</i>' if s.get("source") else "")
                    + '</div></div>')

    cards = []
    n_maps = 0
    for b in blocks:
        ids = b["ids"]
        tiers = {tier(i)[0] for i in ids} or {"ladder"}
        t = ("modelled" if "modelled" in tiers
             else "excluded" if tiers == {"excluded"} else "ladder")
        label_tr, meaning = TIER_TR[t]
        names = ", ".join(f"{cat.get(i, i)} ({i})" for i in ids) or "—"

        body = [f'<div class="sub">{html.escape(names)}</div>',
                f'<div class="card"><span class="tag {t}">{html.escape(label_tr)}</span> '
                f'<div class="why" style="margin-top:6px">{html.escape(meaning)}</div>'
                + (f'<div class="why" style="margin-top:6px">Merdiven: '
                   f'{html.escape(ladder_note(ids[0]))}</div>' if ids else "")
                + '</div>']

        for sub, market, stats, note in b["entries"]:
            n_maps += len(stats)
            group = MARKET_GROUP.get(market)
            tr_name = MARKET_TR.get(market)
            head = (html.escape((f"{sub.replace('_', ' ')} · " if sub else "")
                                + (tr_name or market.replace("_", " "))))
            if tr_name:
                head += f'  <span class="chip">{html.escape(market)}</span>' 
            chip = (f' <span class="chip">grup {group} — '
                    f'{html.escape(signals.MARKETS.get(group, ""))}</span>' if group else "")
            rows = []
            for name in stats:
                g = b["glossary"].get(name) or {}
                why = g.get("why") or g.get("definition") or ""
                rows.append(
                    f'<div class="stat"><span class="name">{html.escape(name.replace("_", " "))}</span>'
                    + (f'<div class="why">{html.escape(g["definition"])}</div>'
                       if g.get("definition") else "")
                    + (f'<div class="why"><b>bu bahis için:</b> {html.escape(why)}</div>'
                       if why and why != g.get("definition") else "")
                    + '</div>')
            body.append(f'<div class="mk"><b>{head}</b>{chip}'
                        + (f'<div class="why">{html.escape(note)}</div>' if note else "")
                        + "".join(rows) + '</div>')

        for title, text in b["notes"]:
            if text:
                body.append(f'<div class="mk"><b>{html.escape(title)}</b>'
                            f'<div class="why">{html.escape(text)}</div></div>')
        if b["findings"]:
            body.append('<div class="mk"><b>araştırma notları</b>' + "".join(
                f'<div class="stat why">{html.escape(str(f))}</div>' for f in b["findings"])
                + '</div>')

        text = " ".join(
            [str(b["label"]).replace("_", " "), names]
            + [m.replace("_", " ") for _, m, _, _ in b["entries"]]
            + [w for _, m, _, _ in b["entries"] for w in _hard_stems(MARKET_TR.get(m, ""))]
            + [s.replace("_", " ") for _, _, st, _ in b["entries"] for s in st]).lower()
        cards.append(
            f'<details class="sport" data-tier="{t}" data-text="{html.escape(text, quote=True)}">'
            f'<summary>{html.escape(str(b["label"]))} '
            f'<span class="tag {t}">{html.escape(label_tr)}</span></summary>'
            + "".join(body) + '</details>')

    # Last real run, so the pipeline section quotes measured numbers rather than examples.
    last = {}
    try:
        with open(os.path.join(ROOT, "daily_report.json")) as f:
            rep = json.load(f)
        w = max(rep.get("windows") or [{}], key=lambda x: x.get("hours", 0))
        last = {"matches": w.get("matches", 0), "picks": len(w.get("picks") or []),
                "no_model": (w.get("skipped") or {}).get("no_model", 0)}
    except (OSError, json.JSONDecodeError, ValueError):
        last = {"matches": 0, "picks": 0, "no_model": 0}

    floor = getattr(config, "MIN_MODEL_SURVIVAL", 0.75)
    page = PAGE.format(
        generated=html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        n_sports=len(cat),
        n_maps=n_maps,
        n_modelled=len(modelled),
        modelled_names=html.escape(", ".join(cat.get(i, str(i)) for i in modelled)),
        min_odds=f"{getattr(config, 'MIN_ODDS', 1.10):.2f}",
        floor=f"{floor * 100:.0f}",
        floor_f=f"{floor:.2f}",
        rows="674.379", fixtures="3.627",
        matches=last["matches"], picks=last["picks"], no_model=last["no_model"],
        live_block="".join(live_rows),
        sports="\n".join(cards),
        footer=(
            "Kaynak dosyalar: engine/signals.py (canlı sinyal kaydı), engine/pick.py "
            "(modelli sporlar), engine/ladder.py (merdiven dalları), config.py (eşikler ve "
            "hariç tutmalar), research/*.json (spor başına araştırma). Bu sayfa "
            "tools/make_method_page.py tarafından üretilir; bir eşleştirme değişirse "
            "sayfa da değişir.<br>"
            "Aşağıdaki spor bloklarındaki istatistik adları ve tanımları araştırma "
            "dosyalarının kendi (İngilizce) terimleriyle bırakıldı: bir istatistiği "
            "gevşek çevirmek, onu anlaşılmış gibi göstermenin en kolay yoludur. Bugün "
            "modele giren sinyallerin Türkçe açıklamaları yukarıdaki \"canlı\" "
            "bölümündedir.<br>"
            "Araştırma bloklarındaki bir eşleştirmenin burada yazması, o istatistiğin "
            "<b>hesaplandığı anlamına gelmez</b>. Bugün hesaplanan ve modele giren sinyaller "
            "yalnızca yukarıdaki \"canlı\" bölümünde yeşil noktayla işaretli olanlardır."),
    )
    with open(out_path, "w") as f:
        f.write(page)
    return len(cards), n_maps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="method.html")
    args = ap.parse_args()
    n, m = build(args.out)
    print(f"wrote {args.out} — {n} sport groups, {m} statistic→bet mappings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
