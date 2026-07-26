#!/usr/bin/env python3
"""Render a day's selections as one filterable page — before and after they settle.

    python tools/make_picks_page.py --report daily_report.json --out picks.html

The Telegram message used to carry every selection, which meant nine messages and no way
to sort, filter or search. It now carries a short notice and this page travels as the
attachment: a ranked list belongs somewhere you can actually work with it.

The same template renders the morning list and the evening scorecard. A pick that carries
a `result` gets a KAZANDI / KAYBETTİ / İADE badge and joins the summary strip, so the day
is judged on the very page that proposed it — a separate results document would let the
two drift apart, and the honest comparison is the whole point of keeping a log.

Self-contained by design — no CDN, no external font, no network at all — because it is
opened from a Telegram attachment on a phone, frequently on a connection that cannot
reach the things a normal page assumes.
"""
import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import tr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE = os.path.join(ROOT, "research", "sports_catalogue.json")

# Sport names live in engine/tr.py with the rest of the user-facing wording. The
# catalogue is the fallback, so a sport added to the book before it is added there still
# labels as its English name rather than as a bare id — an unlabelled "10" in a filter is
# useless.
SPORTS_TR = tr.SPORTS

# engine/grade.py's outcomes, in the words the operator reads them in. Keyed on the exact
# lowercase constants that module emits — an uppercase key here silently matched nothing
# and rendered a settled day as all-pending.
RESULTS_TR = {
    "win": ("KAZANDI", "win"),
    "loss": ("KAYBETTİ", "loss"),
    "push": ("İADE", "push"),
    "half": ("YARIM", "half"),
}
PENDING = "pending"


def sport_names():
    names = dict(SPORTS_TR)
    try:
        with open(CATALOGUE) as f:
            for s in json.load(f).get("sports", []):
                names.setdefault(s["id"], s["name"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return names


PAGE = """<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betwinner analiz — {n} seçim</title>
<style>
 :root {{ color-scheme:light dark; --bg:#fff; --fg:#111; --card:#f6f6f8; --line:#e2e2e6;
          --muted:#666; --accent:#0a7d32; --chip:#eceef2; --win:#0a7d32; --loss:#b3261e;
          --push:#7a5c00; --done:#8f9aa8; }}
 @media (prefers-color-scheme:dark) {{ :root {{ --bg:#0f1115; --fg:#e8e8ea; --card:#181b21;
          --line:#2a2e36; --muted:#9aa0aa; --accent:#3ddc84; --chip:#222630; --win:#3ddc84;
          --loss:#ff8a8a; --push:#e0c064; --done:#6c7684; }} }}
 *{{box-sizing:border-box}}
 body{{margin:0;padding:14px;background:var(--bg);color:var(--fg);
   font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 h1{{font-size:19px;margin:0 0 2px}}
 .sub{{color:var(--muted);font-size:12.5px;margin-bottom:12px}}
 .panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;
   padding:12px;margin-bottom:12px;position:sticky;top:0;z-index:9}}
 .row{{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}}
 label{{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px}}
 select,input{{font:inherit;padding:7px 9px;border-radius:9px;border:1px solid var(--line);
   background:var(--bg);color:var(--fg);min-height:38px}}
 input[type=range]{{padding:0;min-height:26px;width:150px}}
 input[type=checkbox]{{min-height:0;width:18px;height:18px;accent-color:var(--accent);
   margin:0;vertical-align:middle}}
 button{{font:inherit;padding:7px 12px;border-radius:9px;border:1px solid var(--line);
   background:var(--bg);color:var(--fg);min-height:38px;cursor:pointer}}
 button.primary{{background:var(--accent);color:#fff;border-color:transparent;font-weight:600}}
 button:disabled{{opacity:.45;cursor:default}}
 .chip{{background:var(--chip);border-radius:999px;padding:3px 9px;font-size:11.5px;
   color:var(--muted)}}
 .scorecard{{display:flex;flex-wrap:wrap;gap:8px;background:var(--card);
   border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:12px}}
 .stat{{flex:1 1 92px}}
 .stat b{{display:block;font-size:19px;line-height:1.2}}
 .stat span{{font-size:11.5px;color:var(--muted)}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th{{text-align:left;font-size:11.5px;color:var(--muted);text-transform:uppercase;
   letter-spacing:.04em;padding:7px 6px;border-bottom:1px solid var(--line);
   cursor:pointer;white-space:nowrap;user-select:none}}
 th:hover{{color:var(--fg)}}
 td{{padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
 tr.hide{{display:none}}
 tr.done .match, tr.done .pickcell{{color:var(--done)}}
 .id{{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap}}
 .id label{{display:inline-flex;align-items:center;gap:5px;cursor:pointer}}
 .match{{font-weight:600}}
 .meta{{color:var(--muted);font-size:11.5px;margin-top:2px}}
 .pickcell{{max-width:290px}}
 .num{{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}}
 .odds{{font-weight:700}}
 .score{{font-weight:700}}
 .bar{{height:4px;border-radius:3px;background:var(--line);margin-top:4px;overflow:hidden;
   min-width:56px}}
 .bar i{{display:block;height:100%;background:var(--accent)}}
 .badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;
   font-weight:700;letter-spacing:.02em;margin-bottom:3px}}
 .badge.win{{background:var(--win);color:#fff}}
 .badge.loss{{background:var(--loss);color:#fff}}
 .badge.push,.badge.half{{background:var(--push);color:#fff}}
 .badge.pending{{background:var(--chip);color:var(--muted)}}
 a.go{{display:inline-block;padding:6px 10px;border-radius:8px;background:var(--accent);
   color:#fff;text-decoration:none;font-size:12px;font-weight:600;white-space:nowrap}}
 tr.done a.go{{background:var(--done)}}
 .note{{background:var(--card);border:1px solid var(--line);border-radius:10px;
   padding:10px 12px;font-size:12.5px;margin-bottom:12px;color:var(--muted)}}
 .note summary{{cursor:pointer;color:var(--fg);font-weight:600}}
 .note p{{margin:8px 0 0}}
 .empty{{padding:26px 4px;color:var(--muted);text-align:center}}
 footer{{margin-top:16px;color:var(--muted);font-size:11.5px;line-height:1.6}}

 /* Phone layout. The page arrives as a Telegram attachment, so a phone is the normal
    way it gets read — a seven-column table simply runs off the side of one. Each row
    becomes a card instead, with the number, the fixture and the price on the top line. */
 @media (max-width:720px){{
   body{{padding:10px}}
   #t, #t tbody, #t tbody tr, #t td{{display:block}}
   #t thead{{display:none}}
   #t tbody tr{{display:grid;grid-template-columns:auto 1fr auto;gap:3px 9px;
     border:1px solid var(--line);border-radius:12px;padding:11px 12px;margin-bottom:9px;
     align-items:start}}
   #t tbody tr.hide{{display:none}}
   #t td{{border:0;padding:0}}
   #t td:nth-child(1){{grid-area:1/1;font-size:13px;padding-top:1px}}
   #t td:nth-child(2){{grid-area:1/2}}
   #t td:nth-child(4){{grid-area:1/3;font-size:16px}}
   #t td:nth-child(3){{grid-area:2/2/2/4}}
   #t td:nth-child(5){{grid-area:3/2/3/4;text-align:left;margin-top:3px}}
   #t td:nth-child(6){{grid-area:4/1/4/3;align-self:center;text-align:left}}
   #t td:nth-child(7){{grid-area:4/3;text-align:right}}
   .pickcell{{max-width:none}}
   /* Two controls per line, so the sticky panel costs three rows instead of five and
      leaves the phone screen mostly showing selections. Capped in height as well: with
      filters, sorting and the slip queue in it the panel would otherwise take most of a
      phone screen while pinned, and the list is what you came for. */
   .panel{{padding:10px;max-height:46vh;overflow-y:auto}}
   .panel label{{flex:1 1 calc(50% - 4px);min-width:0}}
   .panel select, input[type=range]{{width:100%}}
   label:has(#fText){{flex:1 1 100%}}
 }}
</style></head><body>

<h1>{heading}</h1>
<div class="sub">{generated} · {n} seçim · min oran {min_odds} ·
  model güven eşiği %{floor} · maç başına tek seçim · iadeli bahisler kapalı</div>

{scorecard}
{coverage}

<details class="note">
  <summary>Puan ne demek?</summary>
  <p><b>Puan = modelin bu bahsin tutma olasılığı.</b> 92 puan, "model bunun yaklaşık
  %92 tutacağını söylüyor" demektir. Çevirmen gerekmiyor.</p>
  <p>Tek düzeltme <b>kanıt</b>: aynı olasılıktaki iki seçim eşit sağlamlıkta değildir.
  Biri 12.000 maçla fit edilmiş bir ligde tam isim eşleşmesine dayanır, diğeri 400 maçlık
  bir ligde bulanık eşleşmeye. Kanıt zayıfsa olasılık <b>%{floor} eşiğine doğru geri
  çekilir</b> — ne kadar çekildiği satırda "−x puan" olarak yazar.</p>
  <p style="font-family:ui-monospace,monospace;font-size:12px">
  puan = 100 × ( {floor_f} + (olasılık − {floor_f}) × kanıt )</p>
  <p>Puanlar dar bir bantta toplanır, çünkü listeye giren her seçim zaten %{floor}
  eşiğini geçmiştir. Bu bir kusur değil, ürünün kendisi: bandı kozmetik olarak germek,
  modelin gerçekte ayıramadığı %91 ile %93 arasında yapay bir fark uydurmak olurdu.
  Çubuk, seçimin bu bandın (%{floor}–%100) neresinde durduğunu gösterir.</p>
  <p>Bunlar model çıktısıdır, garanti değil. Yön <b>veriden</b> gelir, orandan değil;
  oran yalnızca {min_odds} alt sınırında okunur. Kitabın fiyatı puana <b>hiç girmez</b>.</p>
</details>

<div class="panel">
  <div class="row">
    <label>Spor
      <select id="fSport"><option value="">hepsi</option>{sport_opts}</select></label>
    <label>Pencere
      <select id="fWindow">{window_opts}</select></label>{result_filter}
    <label>Min puan <span id="vScore" class="chip">0</span>
      <input type="range" id="fScore" min="0" max="100" step="1" value="0"></label>
    <label>Min oran <span id="vOdds" class="chip">1.00</span>
      <input type="range" id="fOdds" min="100" max="300" step="1" value="100"></label>
    <label>Sırala
      <select id="fSort">
        <option value="score:desc">Puan (yüksek → düşük)</option>
        <option value="score:asc">Puan (düşük → yüksek)</option>
        <option value="odds:asc">Oran (düşük → yüksek)</option>
        <option value="odds:desc">Oran (yüksek → düşük)</option>
        <option value="start:asc">Başlangıç (yakın önce)</option>
        <option value="match:asc">Maç (A → Z)</option>
      </select></label>
    <label>Ara
      <input type="search" id="fText" placeholder="takım / lig / bahis"></label>
    <button id="reset" type="button">sıfırla</button>
  </div>
  <div class="row" style="margin-top:8px">
    <span class="chip" id="count"></span>
    <span class="chip">masaüstünde sütun başlıklarından da sıralanır</span>
  </div>
  <div class="row" style="margin-top:8px">
    <button id="selAll" type="button">görünenleri seç</button>
    <button id="selNone" type="button">seçimi temizle</button>
    <button id="next" class="primary" type="button" disabled>sıradakini aç</button>
    <span class="chip" id="queue">0 seçili</span>
    <span class="chip" id="combo"></span>
  </div>
</div>

<table id="t">
<thead><tr>
  <th data-k="id" class="num">#</th>
  <th data-k="match">Maç</th>
  <th data-k="pick">Tercih</th>
  <th data-k="odds" class="num">Oran</th>
  <th data-k="score" class="num">Puan</th>
  <th data-k="start" class="num">Başlangıç (UTC)</th>
  <th></th>
</tr></thead>
<tbody>{rows}</tbody></table>
<div class="empty" id="empty" hidden>Bu filtrelerle seçim kalmadı.</div>

<footer>{footer}</footer>

<script>
var rows=[].slice.call(document.querySelectorAll('#t tbody tr'));
var body=document.querySelector('#t tbody');
var DAY={day};
function num(el,k){{return parseFloat(el.dataset[k])||0}}
function shown(){{return rows.filter(function(r){{return !r.classList.contains('hide')}})}}

function apply(){{
  var sp=document.getElementById('fSport').value,
      w=document.getElementById('fWindow').value,
      sc=+document.getElementById('fScore').value,
      od=+document.getElementById('fOdds').value/100,
      rf=document.getElementById('fResult'),
      res=rf?rf.value:'',
      q=document.getElementById('fText').value.toLowerCase().trim();
  document.getElementById('vScore').textContent=sc;
  document.getElementById('vOdds').textContent=od.toFixed(2);
  var n=0;
  rows.forEach(function(r){{
    var ok = (!sp||r.dataset.sport===sp)
      && (!w||num(r,'window')<=+w)
      && (!res||r.dataset.result===res)
      && num(r,'score')>=sc && num(r,'odds')>=od
      && (!q||r.dataset.text.indexOf(q)>=0);
    r.classList.toggle('hide',!ok); if(ok)n++;
  }});
  document.getElementById('count').textContent=n+' / '+rows.length+' seçim';
  document.getElementById('empty').hidden = n>0;
}}
['fSport','fWindow','fScore','fOdds','fText','fResult'].forEach(function(id){{
  var el=document.getElementById(id); if(el) el.addEventListener('input',apply);
}});

// Sorting lives in the panel, not only in the column headers: on a phone the header row
// is hidden entirely by the card layout, so header clicks are a desktop shortcut and this
// select is the path that works everywhere.
function sortBy(k,asc){{
  rows.sort(function(a,b){{
    // Number() and not parseFloat(): parseFloat('2026-07-26T15:00') happily returns 2026,
    // so the timestamps sorted by YEAR and every fixture tied. Number() rejects the whole
    // string, which is what sends dates down the text branch where they belong.
    var x=a.dataset[k],y=b.dataset[k],nx=Number(x),ny=Number(y),r;
    if(x!==''&&y!==''&&isFinite(nx)&&isFinite(ny)) r=nx-ny;
    else r=String(x).localeCompare(String(y),'tr');
    return asc?r:-r;
  }});
  rows.forEach(function(r){{body.appendChild(r)}});
}}
document.getElementById('fSort').addEventListener('change',function(){{
  var v=this.value.split(':'); sortBy(v[0],v[1]==='asc');
}});
var dir={{}};
document.querySelectorAll('#t th[data-k]').forEach(function(th){{
  th.addEventListener('click',function(){{
    var k=th.dataset.k; dir[k]=!dir[k]; sortBy(k,dir[k]);
  }});
}});

/* Adding the slip. Betwinner has no unauthenticated way to load a betslip — /en/user/coupon
   redirects to login — so "one tap adds all of them" is not on offer without driving a
   logged-in session with the operator's credentials, which this tool deliberately does not
   do. This is the honest fastest version: tick the ones you want, then keep pressing one
   button. Each press opens the next fixture, so it is one tap per leg with no scrolling,
   searching or losing your place, and the site's own betslip accumulates as you go.
   Progress is remembered per day, so closing the page does not restart the queue. */
var KEY='bw-added-'+DAY;
var added={{}};
try {{ added=JSON.parse(localStorage.getItem(KEY)||'{{}}') }} catch(e) {{ added={{}} }}
function save(){{ try {{ localStorage.setItem(KEY,JSON.stringify(added)) }} catch(e) {{}} }}
function checked(){{
  return rows.filter(function(r){{
    var c=r.querySelector('.sel'); return c&&c.checked;
  }});
}}
function pending(){{ return checked().filter(function(r){{ return !added[r.dataset.key] }}) }}
function refresh(){{
  rows.forEach(function(r){{ r.classList.toggle('done',!!added[r.dataset.key]) }});
  var c=checked().length, p=pending().length;
  document.getElementById('queue').textContent = c ? (c-p)+' / '+c+' eklendi' : '0 seçili';
  document.getElementById('next').disabled = p===0;
  var combo=1, legs=0;
  checked().forEach(function(r){{ combo*=num(r,'odds'); legs++; }});
  document.getElementById('combo').textContent =
    legs>1 ? legs+' bacak · kombine oran '+combo.toFixed(2) : '';
}}
document.addEventListener('change',function(e){{ if(e.target.classList.contains('sel')) refresh() }});
document.getElementById('selAll').addEventListener('click',function(){{
  shown().forEach(function(r){{ var c=r.querySelector('.sel'); if(c) c.checked=true }}); refresh();
}});
document.getElementById('selNone').addEventListener('click',function(){{
  rows.forEach(function(r){{ var c=r.querySelector('.sel'); if(c) c.checked=false }}); refresh();
}});
document.getElementById('next').addEventListener('click',function(){{
  var q=pending(); if(!q.length) return;
  // Sıradakini listedeki sırasıyla al, ekranda görünen sırayla değil-tekrar sıralasan bile
  // kuyruk kaybolmasın.
  var r=q[0], a=r.querySelector('a.go');
  added[r.dataset.key]=1; save(); refresh();
  r.scrollIntoView({{block:'center',behavior:'smooth'}});
  if(a) window.open(a.href,'_blank','noopener');
}});

document.getElementById('reset').addEventListener('click',function(){{
  document.getElementById('fSport').value='';
  document.getElementById('fWindow').selectedIndex=0;
  document.getElementById('fScore').value=0;
  document.getElementById('fOdds').value=100;
  document.getElementById('fText').value='';
  document.getElementById('fSort').selectedIndex=0;
  var rf=document.getElementById('fResult'); if(rf) rf.value='';
  sortBy('score',false);
  apply();
}});
apply(); refresh();
</script>
</body></html>"""

ROW = """<tr data-sport="{sport_id}" data-window="{window}" data-score="{score}"
 data-odds="{odds}" data-id="{id}" data-match="{match_sort}" data-pick="{pick_sort}"
 data-start="{start_sort}" data-text="{text}" data-result="{result_key}" data-key="{key}">
 <td class="id num"><label><input type="checkbox" class="sel"><span>{id}</span></label></td>
 <td><div class="match">{match}</div><div class="meta">{sport} · {league}</div></td>
 <td class="pickcell">{badge}{pick}<div class="meta">{scope}{warn}{final}</div></td>
 <td class="num odds">{odds_txt}</td>
 <td class="num"><span class="score">{score_txt}</span>
   <div class="bar"><i style="width:{bar}%"></i></div>
   <div class="meta">{band} · kanıt {ep}{penalty}</div></td>
 <td class="num meta">{start}</td>
 <td>{link}</td>
</tr>"""

SCORECARD = """<div class="scorecard">
  <div class="stat"><b>{hit}</b><span>isabet ({decided} sonuçlanan üzerinden)</span></div>
  <div class="stat"><b style="color:var(--win)">{win}</b><span>kazandı</span></div>
  <div class="stat"><b style="color:var(--loss)">{loss}</b><span>kaybetti</span></div>
  <div class="stat"><b style="color:var(--push)">{push}</b><span>iade / yarım</span></div>
  <div class="stat"><b>{pending}</b><span>bekliyor</span></div>
  <div class="stat"><b>{roi}</b><span>1 birimlik bahislerde getiri</span></div>
</div>"""


def _fmt_pct(x):
    return "—" if x is None else f"%{100.0 * x:.1f}"


def build(report, out_path):
    """Write the page. Returns how many selections it carries."""
    windows = {w["hours"]: w for w in report.get("windows", []) if w.get("hours")}
    if not windows:
        windows = {48: {"hours": 48, "picks": []}}
    longest = max(windows)
    picks = windows[longest].get("picks") or []

    # Which window each selection FIRST appears in, so "next 24 hours" is a real filter
    # rather than a second copy of the list. Ids are assigned once across the whole card
    # upstream, which is what makes this lookup possible at all.
    first_seen = {}
    for hours in sorted(windows):
        for p in windows[hours].get("picks") or []:
            first_seen.setdefault(p.get("id"), hours)

    names = sport_names()
    sports_present = sorted({p.get("sport_id") for p in picks if p.get("sport_id")})
    sport_opts = "".join(
        f'<option value="{s}">{html.escape(str(names.get(s, s)))}</option>'
        for s in sports_present)
    window_opts = "".join(
        f'<option value="{h}"{"" if h != longest else " selected"}>{h} saat</option>'
        for h in sorted(windows, reverse=True))

    floor_pct = (report.get("min_model_survival") or 0.75) * 100.0
    settled = [p for p in picks if p.get("result")]
    rows = []
    for p in picks:
        st = p.get("settlement") or {}
        url = p.get("url")
        match = (f"{p['p1']} - {p['p2']}" if p.get("p1") and p.get("p2")
                 else str(p.get("match") or ""))
        sport = str(names.get(p.get("sport_id"), p.get("sport_id") or ""))
        label, css = RESULTS_TR.get(p.get("result") or "", ("", ""))
        final = p.get("final_score")
        rows.append(ROW.format(
            sport_id=p.get("sport_id", ""),
            window=first_seen.get(p.get("id"), longest),
            score=p.get("score") or 0,
            odds=p.get("odds") or 0,
            id=p.get("id") or "",
            key=html.escape(str(p.get("id") or match), quote=True),
            result_key=p.get("result") or (PENDING if settled else ""),
            match_sort=html.escape(match, quote=True),
            pick_sort=html.escape(str(p.get("selection_tr") or ""), quote=True),
            start_sort=html.escape(str(p.get("start") or ""), quote=True),
            text=html.escape(
                f"{match} {p.get('league') or ''} {p.get('selection_tr') or ''} {sport}".lower(),
                quote=True),
            match=html.escape(match),
            sport=html.escape(sport),
            league=html.escape(str(p.get("league") or "")),
            badge=(f'<span class="badge {css}">{label}</span> ' if label
                   else ('<span class="badge pending">BEKLİYOR</span> ' if settled else "")),
            pick=html.escape(str(p.get("selection_tr") or p.get("selection") or "")),
            scope=html.escape(str(st.get("scope") or "")),
            warn=" ⚠ teyit gerek" if st.get("needs_confirmation") else "",
            final=(f" · maç sonucu {int(final[0])}-{int(final[1])}"
                   if isinstance(final, (list, tuple)) and len(final) == 2 else ""),
            odds_txt=f"{p.get('odds') or 0:.2f}",
            score_txt=f"{p.get('score') or 0:.0f}",
            # The bar is scaled over the band a selection can actually occupy — floor to
            # certainty — because every score starts above the floor and a bar drawn from
            # zero would sit near-full for the weakest pick on the card.
            bar=f"{max(0.0, min(100.0, (float(p.get('score') or floor_pct) - floor_pct) / max(1e-9, 100.0 - floor_pct) * 100.0)):.0f}",
            band=html.escape(str(p.get("band") or "")),
            ep=f"%{p.get('evidence_pct') or 0:.0f}",
            penalty=(f" (−{p['evidence_penalty']:.1f} puan)"
                     if (p.get("evidence_penalty") or 0) >= 0.5 else ""),
            start=html.escape(str(p.get("start") or "")[:16].replace("T", " ")),
            link=(f'<a class="go" href="{html.escape(url, quote=True)}" target="_blank" '
                  f'rel="noopener">Aç</a>') if url else "",
        ))

    summary = report.get("summary")
    scorecard = ""
    if summary:
        scorecard = SCORECARD.format(
            hit=_fmt_pct(summary.get("hit_rate")),
            decided=(summary.get("win", 0) + summary.get("half", 0)
                     + summary.get("loss", 0)),
            win=summary.get("win", 0), loss=summary.get("loss", 0),
            push=summary.get("push", 0) + summary.get("half", 0),
            pending=len(picks) - len(settled),
            roi=(f"{summary['returned'] / summary['staked']:.3f}x"
                 if summary.get("staked") else "—"),
        )
    result_filter = ""
    if settled:
        result_filter = """
    <label>Sonuç
      <select id="fResult"><option value="">hepsi</option>
        <option value="win">kazandı</option><option value="loss">kaybetti</option>
        <option value="push">iade</option><option value="half">yarım</option>
        <option value="pending">bekliyor</option></select></label>"""

    # The count the model could NOT reach is the honest headline of this product, so it
    # goes on the page rather than being quietly left out of it.
    cov = report.get("coverage") or []
    if cov:
        modelled = [c for c in cov if c["state"] == "modelled"]
        gap = [c for c in cov if c["state"] == "no_model"]
        rows.append("")  # keep the table markup separate from the note below
        cov_note = (
            f'<div class="note"><b>Kapsam.</b> Kartta {len(cov)} spor var; '
            f'{len(modelled)} tanesi modelli ve '
            f'{sum(c["matches"] for c in modelled)} maça ulaşılıyor. '
            f'Modeli olmayan {len(gap)} sporda '
            f'{sum(c["matches"] for c in gap)} maç var — bunlardan seçim ÇIKMAZ. '
            + "; ".join(f'{html.escape(c["sport"])} ({c["matches"]} maç: '
                        f'{html.escape(c["detail"])})' for c in gap[:6])
            + '</div>')
        rows.pop()
    else:
        cov_note = ""

    sk = windows[longest].get("skipped") or {}
    foot = [
        f"{windows[longest].get('matches', 0)} maç tarandı · "
        f"modelsiz {sk.get('no_model', 0)} · eşiği geçemeyen "
        f"{sk.get('no_confident_rung', 0)} · modeli olmayan spor "
        f"{sk.get('unmodelled_sport', 0)}",
        "Bir maçta modelin güvenli bir görüşü yoksa o maçtan seçim ÇIKMAZ; "
        "listeyi doldurmak için en az kötü seçenek eklenmez.",
        "Kupona ekleme: Betwinner'ın kimlik doğrulaması olmadan kupon yükleyen bir ucu "
        "yok, bu yüzden tek dokunuşta hepsini ekleyen bir yol da yok. Bunun yerine "
        "istediklerini işaretle ve <b>sıradakini aç</b>'a basmaya devam et — bacak başına "
        "tek dokunuş, ilerleme hatırlanır.",
    ]
    if settled:
        foot.append("Sonuçlar futbolda football-data.co.uk, masa tenisinde kendi "
                    "topladığımız skorlarla işlenir. Sonuçlanamayan bir seçim KAZANDI ya "
                    "da KAYBETTİ sayılmaz, bekliyor kalır.")
    if report.get("link_host"):
        foot.append(f"bağlantılar {html.escape(str(report['link_host']))} üzerinden — "
                    f"Betwinner erişilebilir alan adını değiştirdiğinde otomatik güncellenir")

    generated = str(report.get("generated") or datetime.now(timezone.utc).isoformat())
    page = PAGE.format(
        n=len(picks),
        heading=html.escape(report.get("heading") or "Betwinner günlük analiz"),
        generated=html.escape(generated[:16].replace("T", " ") + " UTC"),
        day=json.dumps(str(report.get("day") or generated[:10])),
        min_odds=f"{report.get('min_odds') or 1.10:.2f}",
        floor=f"{floor_pct:.0f}",
        floor_f=f"{floor_pct / 100.0:.2f}",
        sport_opts=sport_opts,
        window_opts=window_opts,
        result_filter=result_filter,
        scorecard=scorecard,
        coverage=cov_note,
        rows="\n".join(rows),
        footer="<br>".join(foot),
    )
    with open(out_path, "w") as f:
        f.write(page)
    return len(picks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="daily_report.json")
    ap.add_argument("--out", default="picks.html")
    args = ap.parse_args()

    with open(args.report) as f:
        report = json.load(f)
    n = build(report, args.out)
    print(f"wrote {args.out} — {n} selections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
