#!/usr/bin/env python3
"""Render the ranked parlay as a phone-friendly page of Betwinner deep links.

    python tools/make_coupon.py --input data/betwinner_48h.json.gz --legs 50

Betwinner has no unauthenticated way to load a betslip: the coupon endpoints redirect
to login, so "one tap adds all fifty" would require driving a logged-in session with
the operator's credentials. This does the honest version instead — one tap per
selection, opening that fixture on Betwinner, with the page remembering which ones you
have already added.

The mandatory hard-rule-4 figures are rendered at the top of the page, not buried.
"""
import argparse
import gzip
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from engine import bwfeed, parlay, parser, score, settlement  # noqa: E402

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betwinner kupon — {n} seçim</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --card:#f5f5f7; --line:#ddd;
           --accent:#0a7d32; --warn:#8a1c1c; --warnbg:#fdeaea; --muted:#666; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#111; --fg:#eee; --card:#1c1c1e; --line:#333;
             --accent:#3ddc84; --warn:#ff8a8a; --warnbg:#2a1414; --muted:#999; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg);
         font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  h1 {{ font-size:19px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:14px; }}
  .warn {{ background:var(--warnbg); color:var(--warn); border-radius:10px;
           padding:12px 14px; font-size:13.5px; margin-bottom:16px; }}
  .warn b {{ display:block; margin-bottom:6px; font-size:14.5px; }}
  .warn table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  .warn td {{ padding:2px 0; font-variant-numeric:tabular-nums; }}
  .warn td:last-child {{ text-align:right; font-weight:600; }}
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
  .settle.warn {{ color:var(--warn); }}
  a.go {{ display:block; margin-top:10px; text-align:center; text-decoration:none;
          background:var(--accent); color:#fff; padding:12px; border-radius:10px;
          font-weight:600; min-height:44px; }}
  label.chk {{ display:flex; align-items:center; gap:8px; margin-top:8px;
               font-size:13px; color:var(--muted); }}
  input[type=checkbox] {{ width:22px; height:22px; }}
</style>
<h1>Betwinner kupon — {n} seçim</h1>
<div class="sub">Maç başına tek seçim · minimum oran {min_odds} · üretildi: bu tarama</div>

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
  <div class="pick"><span class="sel">{mtype} — <b>{sel}</b></span><span class="odds">{odds}</span></div>
  {settle}
  {link}
  <label class="chk"><input type="checkbox"> kupona ekledim</label>
</div>"""


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--legs", type=int, default=50)
    ap.add_argument("--min-odds", type=float, default=1.10)
    ap.add_argument("--out", default="coupon.html")
    args = ap.parse_args()

    data = load(args.input)
    src = bwfeed if bwfeed.is_bwfeed(data) else parser
    rows = score.filter_and_score(src.normalize(data, config.BOOK))
    settlement.annotate(rows)
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
        cards.append(CARD.format(
            id=f"{r['fixture_id']}-{r['market_key'][1]}-{r['selection']}",
            i=i,
            match=html.escape(f"{r['p1']} v {r['p2']}"),
            league=html.escape(str(r.get("league") or "")),
            start=html.escape((r.get("start") or "")[:16].replace("T", " ")),
            mtype=html.escape(r["market_type"]),
            sel=html.escape(str(r["selection"])),
            odds=f"{r['odds']:.2f}",
            settle=f'<span class="settle{warn}">{prefix}{html.escape(st.get("detail", ""))}</span>',
            link=link,
        ))

    page = PAGE.format(
        n=s["legs"], min_odds=f"{args.min_odds:.2f}",
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
          f"{len({r['fixture_id'] for r in legs})} distinct fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
