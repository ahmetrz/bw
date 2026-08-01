#!/usr/bin/env python3
"""The record so far, in one page: stats.html.

    python tools/make_stats_page.py --out stats.html

WHY THIS EXISTS SEPARATELY FROM results.html. That page is ONE DAY, marked up — it answers
"how did today go". It cannot answer the question that actually decides whether this tool
is worth running, which is whether the model is right ACROSS days. A day is 20-odd bets
and its hit rate swings twenty points on noise; the only number with any authority is the
cumulative one, and until now it existed nowhere but in a terminal.

Everything here is computed from data/predictions.jsonl, the permanent log. Nothing is
carried forward in a summary file, so the page cannot drift from the record: delete it and
the next run rebuilds it identically.

WHAT IT REPORTS, and the order matters because it is the order the questions get asked in:

  1. THE HEADLINE — hit rate and return over every graded selection. Return is measured
     over what was actually STAKED, hit rate over everything predicted, because a pick
     under the daily cap is still evidence about the model even though no money rode on it.
  2. CALIBRATION — what the model claimed against what happened, banded. This is the only
     table that can say the model is WRONG rather than unlucky, so it is not buried.
  3. BREAK-EVEN against realised. Break-even is arithmetic on the book's own prices and
     asserts nothing; realised is measured. The model's own confidence is deliberately NOT
     put beside them — it is the thing under test, and a product that grades itself against
     its own claim has measured nothing.
  4. The breakdowns — day, sport, market, odds band — which are where a problem localises
     once the headline says there is one.
"""
import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import grade, stake, tr  # noqa: E402

# Below this many settled legs a rate is arithmetic, not evidence. Same threshold the
# daily scorecard uses, for the same reason: this project has twice been steered by a
# bold percentage built from a handful of legs.
MIN_MEANINGFUL = 20

MARKETS = {
    "1": "1X2 galibiyet", "101": "iki yönlü galibiyet", "8": "çifte şans",
    "2": "handikap", "2854": "handikap", "17": "toplam gol",
    "109": "set handikabı", "7099": "set handikabı", "182": "toplam set",
    "2604": "toplam set", "876": "toplam frame", "2436": "toplam harita",
    "2438": "harita handikabı", "15": "takım toplamı", "62": "takım toplamı",
}

ODDS_BANDS = ((1.00, 1.15), (1.15, 1.25), (1.25, 1.40), (1.40, 99.0))
MODEL_BANDS = ((0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01))


def market_of(row):
    return MARKETS.get(str(row.get("market_line", "")).split("|")[0], "diğer")


def summarise(rows):
    """grade.summarize plus the two numbers the page needs and it does not carry."""
    s = grade.summarize(rows)
    if not s:
        return None
    s["roi"] = ((s["returned"] - s["staked"]) / s["staked"]) if s["staked"] else None
    return s


def rows_of(preds, key):
    """[(label, summary)] grouped by `key`, best-populated group first."""
    groups = {}
    for r in preds:
        groups.setdefault(key(r), []).append(r)
    out = [(k, summarise(v)) for k, v in groups.items()]
    return sorted((x for x in out if x[1]), key=lambda x: -x[1]["graded"])


def calibration(decided):
    """[(band, n, claimed, realised)] — the model's word against the outcome."""
    out = []
    for lo, hi in MODEL_BANDS:
        sel = [r for r in decided if lo <= (r.get("model_survival") or 0) < hi]
        if not sel:
            continue
        claimed = sum(r["model_survival"] for r in sel) / len(sel)
        realised = sum(1 for r in sel if r["result"] == grade.WIN) / len(sel)
        out.append((f"%{lo * 100:.0f} – %{hi * 100:.0f}", len(sel), claimed, realised))
    return out


def _pct(x, digits=1):
    return "—" if x is None else f"%{100 * x:.{digits}f}"


def _signed(x):
    return "—" if x is None else f"{100 * x:+.1f}%"


def _cls(x):
    if x is None:
        return ""
    return "good" if x > 0 else ("bad" if x < 0 else "")


def build(preds, out_path):
    graded = [r for r in preds if r.get("result")]
    decided = [r for r in graded if r["result"] in (grade.WIN, grade.LOSS, grade.HALF)]
    total = summarise(graded)
    if not total:
        with open(out_path, "w") as f:
            f.write(EMPTY.format(n=len(preds)))
        return 0

    realised = total["hit_rate"]
    be = stake.break_even_rate([r["odds"] for r in decided])
    pending = len(preds) - len(graded)

    def table(title, pairs, head="", note=""):
        body = "".join(
            ROW.format(label=html.escape(str(k)), n=s["graded"], w=s["win"], l=s["loss"],
                       hit=_pct(s["hit_rate"]), staked=f"{s['staked']:g}",
                       ret=f"{s['returned']:.2f}", roi=_signed(s["roi"]),
                       cls=_cls(s["roi"]))
            for k, s in pairs)
        return TABLE.format(title=html.escape(title), head=head or "", rows=body,
                            note=note)

    cal = calibration(decided)
    cal_rows = "".join(
        CAL_ROW.format(band=b, n=n, claimed=_pct(c), real=_pct(r),
                       gap=f"{100 * (r - c):+.1f}", cls=_cls(r - c))
        for b, n, c, r in cal)

    page = PAGE.format(
        generated=html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        graded=total["graded"], pending=pending, total=len(preds),
        hit=_pct(realised), win=total["win"], loss=total["loss"],
        push=total["push"] + total["half"],
        staked=f"{total['staked']:g}", returned=f"{total['returned']:.2f}",
        roi=_signed(total["roi"]), roi_cls=_cls(total["roi"]),
        caveat=("" if total["graded"] >= MIN_MEANINGFUL
                else SMALL.format(n=total["graded"], need=MIN_MEANINGFUL)),
        breakeven=_pct(be), realised=_pct(realised),
        edge=f"{100 * (realised - be):+.1f}" if (be and realised is not None) else "—",
        edge_cls=_cls((realised - be) if (be and realised is not None) else None),
        cal_rows=cal_rows,
        by_day=table("Güne göre", rows_of(graded, lambda r: r.get("date") or "?")),
        by_sport=table("Spora göre",
                       rows_of(graded, lambda r: tr.sport(r.get("sport_id"),
                                                          str(r.get("sport_id"))))),
        by_market=table("Bahis türüne göre", rows_of(graded, market_of)),
        by_odds=table("Oran bandına göre", [
            (f"{lo:.2f} – {hi:.2f}",
             summarise([r for r in graded if lo <= (r.get("odds") or 0) < hi]))
            for lo, hi in ODDS_BANDS
            if summarise([r for r in graded if lo <= (r.get("odds") or 0) < hi])]),
    )
    with open(out_path, "w") as f:
        f.write(page)
    return total["graded"]


EMPTY = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>Betwinner — birikmiş istatistik</title></head><body>
<h1>Henüz notlandırılmış seçim yok</h1>
<p>{n} tahmin kayıtlı, hiçbiri sonuçlanmamış.</p></body></html>"""

SMALL = ("""<p class="note">Bu oran <b>{n}</b> sonuçlanan seçime dayanıyor. En az {need}"""
         """ seçim sonuçlanana kadar bir performans göstergesi değil.</p>""")

TABLE = """<h2>{title}</h2>{head}
<div class="wrap"><table>
 <thead><tr><th></th><th>not</th><th>K</th><th>X</th><th>isabet</th>
   <th>yatan</th><th>dönen</th><th>getiri</th></tr></thead>
 <tbody>{rows}</tbody></table></div>{note}"""

ROW = """<tr><td class="lbl">{label}</td><td class="num">{n}</td><td class="num">{w}</td>
 <td class="num">{l}</td><td class="num">{hit}</td><td class="num">{staked}</td>
 <td class="num">{ret}</td><td class="num {cls}">{roi}</td></tr>"""

CAL_ROW = """<tr><td class="lbl">{band}</td><td class="num">{n}</td>
 <td class="num">{claimed}</td><td class="num">{real}</td>
 <td class="num {cls}">{gap}</td></tr>"""

PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Betwinner — birikmiş istatistik</title>
<style>
 :root{{--bg:#0f1216;--card:#161b22;--line:#252c36;--fg:#e6edf3;--muted:#8b949e;
   --good:#3fb950;--bad:#f85149}}
 @media (prefers-color-scheme: light){{
   :root{{--bg:#fff;--card:#f6f8fa;--line:#d8dee4;--fg:#1f2328;--muted:#656d76}}}}
 *{{box-sizing:border-box}}
 body{{margin:0;padding:18px;background:var(--bg);color:var(--fg);
   font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 h1{{font-size:20px;margin:0 0 4px}}
 h2{{font-size:15px;margin:26px 0 8px;color:var(--muted);text-transform:uppercase;
   letter-spacing:.04em}}
 .sub{{color:var(--muted);font-size:12.5px;margin-bottom:16px}}
 .cards{{display:flex;flex-wrap:wrap;gap:8px;background:var(--card);
   border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}}
 .stat{{flex:1 1 100px}}
 .stat b{{display:block;font-size:22px;line-height:1.2}}
 .stat span{{font-size:11.5px;color:var(--muted)}}
 .note{{background:var(--card);border:1px solid var(--line);border-radius:10px;
   padding:11px 13px;font-size:12.5px;color:var(--muted);margin:10px 0}}
 .wrap{{overflow-x:auto}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px;min-width:460px}}
 th{{text-align:right;font-size:11px;color:var(--muted);text-transform:uppercase;
   padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}
 th:first-child{{text-align:left}}
 td{{padding:7px 8px;border-bottom:1px solid var(--line)}}
 .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 .lbl{{max-width:230px}}
 .good{{color:var(--good)}} .bad{{color:var(--bad)}}
</style></head><body>

<h1>Birikmiş istatistik</h1>
<div class="sub">{generated} · {graded} seçim sonuçlandı, {pending} bekliyor
  (toplam {total} tahmin)</div>

<div class="cards">
  <div class="stat"><b>{hit}</b><span>isabet</span></div>
  <div class="stat"><b style="color:var(--good)">{win}</b><span>kazandı</span></div>
  <div class="stat"><b style="color:var(--bad)">{loss}</b><span>kaybetti</span></div>
  <div class="stat"><b>{push}</b><span>iade / yarım</span></div>
  <div class="stat"><b>{staked}</b><span>birim oynandı</span></div>
  <div class="stat"><b>{returned}</b><span>birim döndü</span></div>
  <div class="stat"><b class="{roi_cls}">{roi}</b><span>getiri</span></div>
</div>{caveat}

<h2>Başabaş noktası</h2>
<div class="cards">
  <div class="stat"><b>{breakeven}</b><span>bu oranlarda gereken isabet</span></div>
  <div class="stat"><b>{realised}</b><span>gerçekleşen isabet</span></div>
  <div class="stat"><b class="{edge_cls}">{edge} puan</b><span>fark</span></div>
</div>
<p class="note">Başabaş, kitabın <b>kendi fiyatlarına</b> uygulanan aritmetiktir ve hiçbir
iddia taşımaz: eşit miktarla oynanan n bahis, kazananların ortalama oranı kadar döner.
Yanına konan sayı <b>gerçekleşen</b> isabettir — modelin kendi güveni değil, çünkü test
edilen şey odur. Uyarı: bu hesap kısa ve uzun oranlarda kazanma şansının aynı olduğunu
varsayar; kazananlar kısa oranda toplanırsa gerçek getiri bu farkın gösterdiğinden düşük
çıkar. Aşağıdaki oran bandı tablosu tam olarak bunu gösterir.</p>

<h2>Model kalibrasyonu</h2>
<div class="wrap"><table>
 <thead><tr><th>model güven bandı</th><th>n</th><th>model diyor</th>
   <th>gerçekleşen</th><th>fark (puan)</th></tr></thead>
 <tbody>{cal_rows}</tbody></table></div>
<p class="note">Modelin <b>haklı mı</b> olduğunu söyleyebilen tek tablo bu. Güvenli bir
model, doğru bir model demek değildir: basketbolun ilk uyarlaması +12.5 handikaba %90.4
diyordu, gerçek oran %74.9'du, ve güven eşiği bunu asla yakalayamazdı — eşik modele
güvenir. Bir bantta fark kalıcı olarak eksiye kayıyorsa model orada fazla iyimserdir.</p>

{by_day}
{by_sport}
{by_market}
{by_odds}

<p class="note">Getiri <b>oynanan</b> üzerinden, isabet <b>tahmin edilen</b> üzerinden
hesaplanır. Günlük tavanın altında kalan bir seçime para konmaz ama tuttu mu tutmadı mı
yine de modelin doğruluğu hakkında kanıttır — ikisi farklı sorular, farklı kümeler.</p>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", default="data/predictions.jsonl")
    ap.add_argument("--out", default="stats.html")
    args = ap.parse_args()

    preds = []
    if os.path.exists(args.predictions):
        with open(args.predictions) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    preds.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    n = build(preds, args.out)
    print(f"wrote {args.out} — {n} graded of {len(preds)} predictions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
