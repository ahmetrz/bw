"""Shared page shell for the combine-platform's web screens: nav, CSS, escaping helpers.

Deliberately NOT used by the existing tools/make_picks_page.py / make_stats_page.py /
make_method_page.py — those already work, are covered by tests/test_regression.py's exact
content assertions, and touching them risks the live pipeline for a cosmetic nav bar
(docs/DECISIONS/0001). New screens link back to them by relative href; the old screens are
not required to link forward for the new ones to be reachable.

Same non-negotiables as the existing pages, because they are opened from a phone, often
via a Telegram attachment, sometimes offline: ONE file, no external resources (no CDN, no
font, no analytics, no `<script src=`), every dynamic value passed through escape().
"""
import html

NAV = (
    ("combine.html", "Bugünün Kuponu"),
    ("referee.html", "Hakem Kurulu"),
    ("dataquality.html", "Veri Kalitesi"),
    ("scanned.html", "Taranan Karşılaşmalar"),
    ("rejected.html", "Elenen Seçimler"),
    ("combine_history.html", "Geçmiş Kuponlar"),
    ("combine_results.html", "Sonuçlar"),
    ("lab.html", "Performans Laboratuvarı"),
    ("calibration.html", "Güven Kalibrasyonu"),
    ("model_versions.html", "Model Sürümleri"),
    ("proposed_changes.html", "Önerilen Değişiklikler"),
    ("source_health.html", "Veri Kaynağı Sağlığı"),
    ("runs.html", "Çalışma Geçmişi"),
    ("settings.html", "Ayarlar"),
)
# The existing, separately-maintained pages (docs/DECISIONS/0001) — linked, not rebuilt.
LEGACY_NAV = (
    ("picks.html", "Tarama Listesi"),
    ("results.html", "Tarama Sonuçları"),
    ("stats.html", "Tarama İstatistiği"),
    ("method.html", "Yöntem"),
)


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def fmt_pct(x, digits=1):
    return "—" if x is None else f"%{x * 100:.{digits}f}"


def fmt_num(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


CSS = """
:root {
  --bg: #0b0f14; --panel: #121821; --panel2: #171f2a; --border: #232d3a;
  --text: #e6edf3; --muted: #8b98a5; --accent: #4fb0ff; --accent2: #7ee0c3;
  --warn: #f0b429; --bad: #ff6b6b; --good: #58d68d;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #f5f7fa; --panel: #ffffff; --panel2: #eef1f5; --border: #dde3ea;
          --text: #16202b; --muted: #5b6b7a; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--sans);
       line-height: 1.5; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header { position: sticky; top: 0; z-index: 5; background: var(--panel);
         border-bottom: 1px solid var(--border); padding: 10px 14px; }
header .brand { font-weight: 700; letter-spacing: .02em; }
nav { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 8px; font-size: 13px; }
nav a { color: var(--muted); padding: 3px 0; }
nav a.active { color: var(--accent); font-weight: 600; }
nav .sep { color: var(--border); }
main { max-width: 1100px; margin: 0 auto; padding: 18px 14px 60px; }
h1 { font-size: 20px; margin: 6px 0 14px; }
h2 { font-size: 16px; margin: 26px 0 10px; color: var(--accent2); }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
        padding: 14px 16px; margin-bottom: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 10px; }
.stat { background: var(--panel2); border-radius: 8px; padding: 10px 12px; }
.stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase;
               letter-spacing: .04em; }
.stat .value { font-family: var(--mono); font-size: 20px; margin-top: 2px; }
.tablewrap { width: 100%; overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); }
table { border-collapse: collapse; width: 100%; min-width: 480px; font-size: 13px; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--border); text-align: left;
         white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; }
tr:last-child td { border-bottom: none; }
.mono { font-family: var(--mono); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
         font-weight: 700; }
.badge.win, .badge.approve, .badge.ok { background: rgba(88,214,141,.15); color: var(--good); }
.badge.loss, .badge.veto, .badge.bad { background: rgba(255,107,107,.15); color: var(--bad); }
.badge.push, .badge.flag, .badge.warn { background: rgba(240,180,41,.15); color: var(--warn); }
.badge.pending { background: rgba(139,152,165,.15); color: var(--muted); }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.empty { text-align: center; padding: 40px 20px; color: var(--muted); }
.pill { display: inline-block; background: var(--panel2); border: 1px solid var(--border);
        border-radius: 999px; padding: 2px 10px; font-size: 12px; margin: 2px 4px 2px 0; }
details { margin: 6px 0; }
details summary { cursor: pointer; color: var(--accent); }
footer { max-width: 1100px; margin: 30px auto 0; padding: 14px; color: var(--muted);
         font-size: 12px; border-top: 1px solid var(--border); }
"""


def _nav_link(href, label, active):
    cls = ' class="active"' if href == active else ""
    return f'<a href="{esc(href)}"{cls}>{esc(label)}</a>'


def page(title, active, body, subtitle=None):
    """A full, self-contained HTML document. `active` is the current nav href."""
    nav_html = ' <span class="sep">·</span> '.join(
        _nav_link(href, label, active) for href, label in NAV)
    legacy_html = ' <span class="sep">·</span> '.join(
        _nav_link(href, label, active) for href, label in LEGACY_NAV)
    sub = f'<div class="small muted">{esc(subtitle)}</div>' if subtitle else ""
    return f"""<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Kombine Platformu</title>
<style>{CSS}</style>
</head><body>
<header>
  <div class="brand">⚽🎾 Futbol &amp; Tenis Kombine Platformu</div>
  <nav>{nav_html}</nav>
  <nav class="small">{legacy_html}</nav>
</header>
<main>
<h1>{esc(title)}</h1>
{sub}
{body}
</main>
<footer>
  Kişisel karar desteği aracı. Kesin kazanç veya risksiz bahis iddiası içermez.
  Geçmiş performans gelecekteki başarının garantisi değildir. Otomatik bahis
  verilmez — kupon kodu yalnızca Betwinner'ın kendi arayüzüne elle girilmek içindir.
</footer>
</body></html>"""


def empty_state(message):
    return f'<div class="card empty">{esc(message)}</div>'


def stat(label, value):
    return f'<div class="stat"><div class="label">{esc(label)}</div>' \
           f'<div class="value">{esc(value)}</div></div>'
