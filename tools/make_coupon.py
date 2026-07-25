#!/usr/bin/env python3
"""Render the ranked parlay as a phone-friendly page of Betwinner deep links.

    python tools/make_coupon.py --input data/betwinner_48h.json.gz --legs 50
    python tools/make_coupon.py --input data/betwinner_48h.json.gz --hours 12 --sports 1,3

Betwinner has no unauthenticated way to load a betslip: the coupon endpoints redirect to
login, so "one tap adds all fifty" would require driving a logged-in session with the
operator's credentials. This does the honest version instead — one tap per selection,
opening that fixture on Betwinner, with the page remembering which ones you have already
added.

The mandatory hard-rule-4 figures are rendered at the top of the page, not buried, and so
is the basis on which the selections were chosen. That second part matters: these are
ranked by how cheap the market is inside Betwinner's own line, which is NOT a forecast of
who wins, and the page has to say so rather than let a tidy list imply otherwise.
"""
import argparse
import gzip
import html
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import bwfeed, parlay, parser, score, settlement, tr  # noqa: E402

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betwinner kupon — {n} seçim</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --card:#f5f5f7; --line:#ddd;
           --accent:#0a7d32; --warn:#8a1c1c; --warnbg:#fdeaea; --muted:#666;
           --note:#0b4a8f; --notebg:#eaf2fd; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#111; --fg:#eee; --card:#1c1c1e; --line:#333;
             --accent:#3ddc84; --warn:#ff8a8a; --warnbg:#2a1414; --muted:#999;
             --note:#9dc8ff; --notebg:#12233a; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg);
         font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  h1 {{ font-size:19px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:14px; }}
  .warn {{ background:var(--warnbg); color:var(--warn); border-radius:10px;
           padding:12px 14px; font-size:13.5px; margin-bottom:12px; }}
  .warn b {{ display:block; margin-bottom:6px; font-size:14.5px; }}
  .warn table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  .warn td {{ padding:2px 0; font-variant-numeric:tabular-nums; }}
  .warn td:last-child {{ text-align:right; font-weight:600; }}
  .note {{ background:var(--notebg); color:var(--note); border-radius:10px;
           padding:12px 14px; font-size:13.5px; margin-bottom:16px; }}
  .note b {{ display:block; margin-bottom:6px; font-size:14.5px; }}
  .bar {{ position:sticky; top:0; background:var(--bg); padding:10px 0;
          border-bottom:1px solid var(--line); margin-bottom:10px; font-size:14px;
          display:flex; justify-content:space-between; align-items:center; z-index:5; }}
  .bar button {{ font-size:13px; padding:6px 10px; border-radius:8px;
                 border:1px solid var(--line); background:var(--card); color:var(--fg); }}
  .card {{ background:var(--card); border-radius:12px; padding:12px 14px;
           margin-bottom:10px; border:1px solid var(--line); }}
  .card.done {{ opacity:.45; }}
  .row {{ display:flex; align-items:center; gap:12px; }}
  .idx {{ font-size:12px; color:var(--muted); min-width:24px; }}
  .match {{ font-weight:600; }}
  .meta {{ font-size:12.5px; color:var(--muted); margin-top:2px; }}
  .pick {{ margin-top:8px; display:flex; align-items:center;
           justify-content:space-between; gap:10px; }}
  .sel {{ font-size:14.5px; }}
  .odds {{ font-size:19px; font-weight:700; font-variant-numeric:tabular-nums; }}
  .settle {{ font-size:12px; color:var(--muted); margin-top:6px; line-height:1.35; }}
  .settle.warn {{ color:var(--warn); background:none; padding:0; border-radius:0; }}
  .rung {{ font-size:12px; color:var(--accent); margin-top:4px; font-weight:600; }}
  a.go {{ display:block; margin-top:10px; text-align:center; text-decoration:none;
          background:var(--accent); color:#fff; padding:12px; border-radius:10px;
          font-weight:600; min-height:44px; }}
  label.chk {{ display:flex; align-items:center; gap:8px; margin-top:8px;
               font-size:13px; color:var(--muted); }}
  input[type=checkbox] {{ width:22px; height:22px; }}
</style>
<h1>Betwinner kupon — {n} seçim</h1>
<div class="sub">{scope_line}</div>

<div class="note">
  <b>Bu seçimler neye göre yapıldı?</b>
  {basis}
</div>

<div class="warn">
  <b>Bunlar Betwinner'ın kendi sayıları. Değer iddiası değil.</b>
  Tek kitap içinde bir kombine yapı gereği pozitif beklenti taşıyamaz: her bacak
  kitabın marjını bir kez daha çarpar.
  <table>
    <tr><td>Kombine oran</td><td>{combined_odds}</td></tr>
    <tr><td>Kitabın kendi olasılığı</td><td>{prob} (~1/{one_in})</td></tr>
    <tr><td>Beklenen getiri çarpanı</td><td>{ev}</td></tr>
    <tr><td>Beklenen kayıp</td><td>%{loss}</td></tr>
  </table>
  Ayrıca Betwinner'ın kupon başına <b>maksimum ödeme sınırı</b> ve
  <b>maksimum bacak sayısı</b> kuralları geçerlidir.
</div>

<div class="bar"><span id="prog">0 / {n} eklendi</span>
  <button onclick="if(confirm('İşaretler sıfırlansın mı?')){{localStorage.clear();location.reload()}}">Sıfırla</button>
</div>
{cards}
<script>
  var K='bwcoupon:{sig}';
  var done=JSON.parse(localStorage.getItem(K)||'{{}}');
  function paint(){{
    var n=0;
    document.querySelectorAll('.card').forEach(function(c){{
      var id=c.dataset.id, on=!!done[id];
      c.classList.toggle('done',on);
      c.querySelector('input').checked=on;
      if(on)n++;
    }});
    document.getElementById('prog').textContent=n+' / {n} eklendi';
  }}
  document.querySelectorAll('.card input').forEach(function(cb){{
    cb.addEventListener('change',function(){{
      var id=cb.closest('.card').dataset.id;
      if(cb.checked)done[id]=1; else delete done[id];
      localStorage.setItem(K,JSON.stringify(done)); paint();
    }});
  }});
  paint();
</script>
"""

CARD = """<div class="card" data-id="{id}">
  <div class="row"><span class="idx">{i}</span>
    <div><div class="match">{match}</div><div class="meta">{league} · {start}</div></div>
  </div>
  <div class="pick"><span class="sel">{mtype}<br><b>{sel}</b></span><span class="odds">{odds}</span></div>
  {rung}
  {settle}
  {link}
  <label class="chk"><input type="checkbox"> kupona ekledim</label>
</div>"""

# Said plainly, because a ranked list of fifty bets implies a forecast whether or not one
# was made. Ranking is on within-book market cheapness; no model produced these.
BASIS_MARKET_ONLY = (
    "Bu seçimler <b>Betwinner'ın kendi fiyat yapısına</b> göre sıralandı: her market, "
    "kendi <i>türü</i> içinde ne kadar düşük marjla fiyatlandığına bakılarak puanlandı. "
    "<b>Bu bir maç tahmini değildir</b> — kimin kazanacağına dair bir model çıktısı "
    "içermez. Yön veren bir istatistik modeli devreye girene kadar, güvenli-forma "
    "merdiveni (kaybetmez / +handikap / set alır) uygulanamaz, çünkü merdivenin "
    "çalışması için önce veriden gelen bir yön gerekir. "
    "Oranın tek kullanıldığı yer 1.10 alt sınırıdır."
)


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--legs", type=int, default=50)
    ap.add_argument("--min-odds", type=float, default=1.10)
    ap.add_argument("--hours", type=float, default=0.0,
                    help="only fixtures starting within N hours (0 = no limit)")
    ap.add_argument("--sports", default="", help="csv of sport ids to keep; blank = all")
    ap.add_argument("--out", default="coupon.html")
    args = ap.parse_args()

    data = load(args.input)
    src = bwfeed if bwfeed.is_bwfeed(data) else parser
    rows = score.filter_and_score(src.normalize(data, config.BOOK))
    settlement.annotate(rows)

    scope_bits = [f"maç başına tek seçim", f"minimum oran {args.min_odds:.2f}"]

    wanted = {int(s) for s in args.sports.split(",") if s.strip()}
    if wanted:
        rows = [r for r in rows if r.get("sport_id") in wanted]
        scope_bits.append("spor filtresi: " + ",".join(str(s) for s in sorted(wanted)))
    if args.hours:
        cutoff = time.time() + args.hours * 3600
        kept = []
        for r in rows:
            start = r.get("start")
            if not start:
                continue
            try:
                from datetime import datetime
                if datetime.fromisoformat(start).timestamp() <= cutoff:
                    kept.append(r)
            except ValueError:
                continue
        rows = kept
        scope_bits.append(f"önümüzdeki {args.hours:g} saat")

    legs = parlay.build(rows, legs=args.legs, min_odds=args.min_odds)
    s = parlay.summarize(legs)
    if not s:
        print("No legs matched the constraints.", file=sys.stderr)
        return 1

    cards = []
    for i, r in enumerate(legs, 1):
        url = parlay.betwinner_url(r)
        link = (f'<a class="go" href="{html.escape(url)}" target="_blank" '
                f'rel="noopener">Betwinner\'da aç →</a>') if url else \
               '<div class="meta">bağlantı üretilemedi</div>'
        st = r.get("settlement") or settlement.describe(r)
        warn = " warn" if st.get("needs_confirmation") else ""
        prefix = "⚠ " if st.get("needs_confirmation") else ""
        scope_tr = tr.scope(st.get("scope"))
        note = tr.ladder_note(r)
        cards.append(CARD.format(
            id=f"{r['fixture_id']}-{r['market_key'][1]}-{r['selection']}",
            i=i,
            match=html.escape(f"{r['p1']} v {r['p2']}"),
            league=html.escape(str(r.get("league") or "")),
            start=html.escape((r.get("start") or "")[:16].replace("T", " ")),
            mtype=html.escape(tr.market_type(r["market_type"])),
            sel=html.escape(tr.selection(r["selection"])),
            odds=f"{r['odds']:.2f}",
            rung=f'<div class="rung">{html.escape(note)}</div>' if note else "",
            settle=f'<div class="settle{warn}">{prefix}Kapsam: {html.escape(scope_tr)} — '
                   f'{html.escape(tr.settlement(st))}</div>',
            link=link,
        ))

    laddered = sum(1 for r in legs if r.get("ladder_rung"))
    basis = BASIS_MARKET_ONLY
    if laddered:
        basis += (f" Bu kuponda {laddered} seçim modelden gelen bir yönle "
                  f"merdivenden seçildi.")

    page = PAGE.format(
        n=s["legs"], scope_line=html.escape(" · ".join(scope_bits)),
        basis=basis,
        combined_odds=f"{s['combined_odds']:,.2f}x",
        prob=f"{s['combined_book_implied_prob']:.3e}",
        one_in=f"{s['one_in']:,.0f}",
        ev=f"{s['book_expected_return_multiple']:.4f}",
        loss=f"{s['expected_loss_pct']:.2f}",
        sig=f"{s['legs']}-{int(s['combined_odds'])}",
        cards="\n".join(cards),
    )
    with open(args.out, "w") as f:
        f.write(page)

    print(parlay.format_summary(s))
    print(f"\nWrote {args.out} — {s['legs']} legs, "
          f"{len({r.get('match_id', r['fixture_id']) for r in legs})} distinct matches, "
          f"{laddered} from a ladder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
