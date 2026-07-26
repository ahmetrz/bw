#!/usr/bin/env python3
"""Render the day's selections as one filterable page.

    python tools/make_picks_page.py --report daily_report.json --out picks.html

The Telegram message used to carry every selection, which meant nine messages and no way
to sort, filter or search. It now carries a short notice and this page travels as the
attachment: a ranked list belongs somewhere you can actually work with it.

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOGUE = os.path.join(ROOT, "research", "sports_catalogue.json")

# Turkish names for the sports that can actually appear. Anything else falls back to the
# catalogue's English name rather than to a bare id — an unlabelled "10" in a filter is
# useless, and the catalogue is already in the repo.
SPORTS_TR = {
    1: "Futbol", 2: "Buz Hokeyi", 3: "Basketbol", 4: "Tenis", 10: "Masa Tenisi",
    17: "Hokey", 29: "Voleybol", 40: "E-Spor", 71: "Beyzbol", 107: "Hentbol",
}


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
          --muted:#666; --accent:#0a7d32; --chip:#eceef2; }}
 @media (prefers-color-scheme:dark) {{ :root {{ --bg:#0f1115; --fg:#e8e8ea; --card:#181b21;
          --line:#2a2e36; --muted:#9aa0aa; --accent:#3ddc84; --chip:#222630; }} }}
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
 button{{font:inherit;padding:7px 12px;border-radius:9px;border:1px solid var(--line);
   background:var(--bg);color:var(--fg);min-height:38px;cursor:pointer}}
 .chip{{background:var(--chip);border-radius:999px;padding:3px 9px;font-size:11.5px;
   color:var(--muted)}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th{{text-align:left;font-size:11.5px;color:var(--muted);text-transform:uppercase;
   letter-spacing:.04em;padding:7px 6px;border-bottom:1px solid var(--line);
   cursor:pointer;white-space:nowrap;user-select:none}}
 th:hover{{color:var(--fg)}}
 td{{padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
 tr.hide{{display:none}}
 .id{{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}}
 .match{{font-weight:600}}
 .meta{{color:var(--muted);font-size:11.5px;margin-top:2px}}
 .pickcell{{max-width:290px}}
 .num{{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}}
 .odds{{font-weight:700}}
 .score{{font-weight:700}}
 .bar{{height:4px;border-radius:3px;background:var(--line);margin-top:4px;overflow:hidden;
   min-width:56px}}
 .bar i{{display:block;height:100%;background:var(--accent)}}
 a.go{{display:inline-block;padding:6px 10px;border-radius:8px;background:var(--accent);
   color:#fff;text-decoration:none;font-size:12px;font-weight:600;white-space:nowrap}}
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
      leaves the phone screen mostly showing selections. */
   .panel{{padding:10px}}
   .panel label{{flex:1 1 calc(50% - 4px);min-width:0}}
   .panel select, input[type=range]{{width:100%}}
   label:has(#fText){{flex:1 1 100%}}
 }}
</style></head><body>

<h1>Betwinner günlük analiz</h1>
<div class="sub">{generated} · {n} seçim · min oran {min_odds} ·
  model güven eşiği %{floor} · maç başına tek seçim · iadeli bahisler kapalı</div>

<details class="note">
  <summary>Bunlar model çıktısıdır, garanti değil — puan nasıl hesaplanıyor?</summary>
  <p>Yön <b>veriden</b> gelir, orandan değil; oran yalnızca {min_odds} alt sınırında
  okunur. 100 üzerinden puan tamamen analizden hesaplanır ve kitabın fiyatı puana
  <b>hiç girmez</b>: <b>%70 model güveni</b> — modelin bu bahsin tutmasına verdiği
  olasılığın %{floor} eşiğinin ne kadar üzerinde olduğu — artı <b>%30 kanıt</b> —
  takım/oyuncu isim eşleşmesinin gücü ve derecelendirmelerin arkasındaki maç sayısı.
  Aynı güvendeki iki seçim eşit derecede sağlam değildir; puan bunu söyler.</p>
</details>

<div class="panel">
  <div class="row">
    <label>Spor
      <select id="fSport"><option value="">hepsi</option>{sport_opts}</select></label>
    <label>Pencere
      <select id="fWindow">{window_opts}</select></label>
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
function num(el,k){{return parseFloat(el.dataset[k])||0}}
function apply(){{
  var sp=document.getElementById('fSport').value,
      w=document.getElementById('fWindow').value,
      sc=+document.getElementById('fScore').value,
      od=+document.getElementById('fOdds').value/100,
      q=document.getElementById('fText').value.toLowerCase().trim();
  document.getElementById('vScore').textContent=sc;
  document.getElementById('vOdds').textContent=od.toFixed(2);
  var n=0;
  rows.forEach(function(r){{
    var ok = (!sp||r.dataset.sport===sp)
      && (!w||num(r,'window')<=+w)
      && num(r,'score')>=sc && num(r,'odds')>=od
      && (!q||r.dataset.text.indexOf(q)>=0);
    r.classList.toggle('hide',!ok); if(ok)n++;
  }});
  document.getElementById('count').textContent=n+' / '+rows.length+' seçim';
  document.getElementById('empty').hidden = n>0;
}}
['fSport','fWindow','fScore','fOdds','fText'].forEach(function(id){{
  document.getElementById(id).addEventListener('input',apply);
}});

// Sorting lives in the panel, not only in the column headers: on a phone the header row
// is hidden entirely by the card layout, so header clicks are a desktop shortcut and this
// select is the path that works everywhere.
var body=document.querySelector('#t tbody');
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
document.getElementById('reset').addEventListener('click',function(){{
  document.getElementById('fSport').value='';
  document.getElementById('fWindow').selectedIndex=0;
  document.getElementById('fScore').value=0;
  document.getElementById('fOdds').value=100;
  document.getElementById('fText').value='';
  document.getElementById('fSort').selectedIndex=0;
  sortBy('score',false);
  apply();
}});
apply();
</script>
</body></html>"""

ROW = """<tr data-sport="{sport_id}" data-window="{window}" data-score="{score}"
 data-odds="{odds}" data-id="{id}" data-match="{match_sort}" data-pick="{pick_sort}"
 data-start="{start_sort}" data-text="{text}">
 <td class="id num">{id}</td>
 <td><div class="match">{match}</div><div class="meta">{sport} · {league}</div></td>
 <td class="pickcell">{pick}<div class="meta">{scope}{warn}</div></td>
 <td class="num odds">{odds_txt}</td>
 <td class="num"><span class="score">{score_txt}</span>
   <div class="bar"><i style="width:{score}%"></i></div>
   <div class="meta">güven {cp} · kanıt {ep}</div></td>
 <td class="num meta">{start}</td>
 <td>{link}</td>
</tr>"""


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

    rows = []
    for p in picks:
        st = p.get("settlement") or {}
        url = p.get("url")
        match = (f"{p['p1']} - {p['p2']}" if p.get("p1") and p.get("p2")
                 else str(p.get("match") or ""))
        sport = str(names.get(p.get("sport_id"), p.get("sport_id") or ""))
        rows.append(ROW.format(
            sport_id=p.get("sport_id", ""),
            window=first_seen.get(p.get("id"), longest),
            score=p.get("score") or 0,
            odds=p.get("odds") or 0,
            id=p.get("id") or "",
            match_sort=html.escape(match, quote=True),
            pick_sort=html.escape(str(p.get("selection_tr") or ""), quote=True),
            start_sort=html.escape(str(p.get("start") or ""), quote=True),
            text=html.escape(
                f"{match} {p.get('league') or ''} {p.get('selection_tr') or ''} {sport}".lower(),
                quote=True),
            match=html.escape(match),
            sport=html.escape(sport),
            league=html.escape(str(p.get("league") or "")),
            pick=html.escape(str(p.get("selection_tr") or p.get("selection") or "")),
            scope=html.escape(str(st.get("scope") or "")),
            warn=" ⚠ teyit gerek" if st.get("needs_confirmation") else "",
            odds_txt=f"{p.get('odds') or 0:.2f}",
            score_txt=f"{p.get('score') or 0:.0f}",
            cp=f"{p.get('confidence_pct') or 0:.0f}%",
            ep=f"{p.get('evidence_pct') or 0:.0f}%",
            start=html.escape(str(p.get("start") or "")[:16].replace("T", " ")),
            link=(f'<a class="go" href="{html.escape(url, quote=True)}" target="_blank" '
                  f'rel="noopener">Aç</a>') if url else "",
        ))

    # The count the model could NOT reach is the honest headline of this product, so it
    # goes on the page rather than being quietly left out of it.
    sk = windows[longest].get("skipped") or {}
    foot = [
        f"{windows[longest].get('matches', 0)} maç tarandı · "
        f"modelsiz {sk.get('no_model', 0)} · eşiği geçemeyen "
        f"{sk.get('no_confident_rung', 0)} · modeli olmayan spor "
        f"{sk.get('unmodelled_sport', 0)}",
        "Bir maçta modelin güvenli bir görüşü yoksa o maçtan seçim ÇIKMAZ; "
        "listeyi doldurmak için en az kötü seçenek eklenmez.",
    ]
    if report.get("link_host"):
        foot.append(f"bağlantılar {html.escape(str(report['link_host']))} üzerinden — "
                    f"Betwinner erişilebilir alan adını değiştirdiğinde otomatik güncellenir")

    page = PAGE.format(
        n=len(picks),
        generated=html.escape(
            str(report.get("generated") or
                datetime.now(timezone.utc).isoformat())[:16].replace("T", " ") + " UTC"),
        min_odds=f"{report.get('min_odds') or 1.10:.2f}",
        floor=f"{(report.get('min_model_survival') or 0.75) * 100:.0f}",
        sport_opts=sport_opts,
        window_opts=window_opts,
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
