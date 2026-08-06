#!/usr/bin/env python3
"""Render combine.json as a professional PDF report (platform brief section 20).

    python tools/make_pdf_report.py --input combine.json --out combine_report.pdf

Requires reportlab (requirements.txt) — the ONE dependency this project takes, and only
for this. Uses the vendored DejaVu Sans font (assets/fonts/) rather than reportlab's
built-in Helvetica, which is missing ğ/ı/ş and would silently drop or mis-render every
Turkish-specific character in a Turkish-language report.

Covers BOTH outcomes explicitly, per the brief: a produced combine gets the full
per-selection breakdown; a day with none gets an honest explanation of why, how many
matches were scanned, and how many candidates were eliminated and for what reason —
never a blank or apologetic page.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib import colors                                    # noqa: E402
from reportlab.lib.enums import TA_CENTER                           # noqa: E402
from reportlab.lib.pagesizes import A4                              # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm                                  # noqa: E402
from reportlab.pdfbase import pdfmetrics                            # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont                        # noqa: E402
from reportlab.platypus import (HRFlowable, PageBreak, Paragraph,   # noqa: E402
                                Spacer, Table, TableStyle, SimpleDocTemplate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "assets", "fonts")

INK = colors.HexColor("#16202b")
MUTED = colors.HexColor("#5b6b7a")
ACCENT = colors.HexColor("#1f6fb2")
GOOD = colors.HexColor("#1f8a4c")
BAD = colors.HexColor("#c0392b")
LINE = colors.HexColor("#dde3ea")
PANEL = colors.HexColor("#f2f5f8")


def _register_fonts():
    pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold",
                                   os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))


def _styles():
    ss = getSampleStyleSheet()
    for name in ss.byName:
        ss[name].fontName = "DejaVu"
    ss.add(ParagraphStyle("H1", fontName="DejaVu-Bold", fontSize=20, leading=24,
                          textColor=INK, spaceAfter=4))
    ss.add(ParagraphStyle("H2", fontName="DejaVu-Bold", fontSize=13, leading=16,
                          textColor=ACCENT, spaceBefore=14, spaceAfter=6))
    ss.add(ParagraphStyle("Sub", fontName="DejaVu", fontSize=10, leading=13,
                          textColor=MUTED))
    ss.add(ParagraphStyle("Body", fontName="DejaVu", fontSize=9.5, leading=13.5,
                          textColor=INK))
    ss.add(ParagraphStyle("Small", fontName="DejaVu", fontSize=8.3, leading=11.5,
                          textColor=MUTED))
    ss.add(ParagraphStyle("Card", fontName="DejaVu-Bold", fontSize=11, leading=14,
                          textColor=INK))
    ss.add(ParagraphStyle("Center", parent=ss["Body"], alignment=TA_CENTER))
    ss.add(ParagraphStyle("Warn", fontName="DejaVu", fontSize=8.5, leading=12,
                          textColor=BAD))
    return ss


def _fmt_pct(x, digits=1):
    return "—" if x is None else f"%{x * 100:.{digits}f}"


def _fmt_num(x, digits=2):
    return "—" if x is None else f"{x:.{digits}f}"


def _esc(text):
    import html
    return html.escape(str(text))


def _p(text, style):
    return Paragraph(_esc(text) if not isinstance(text, Paragraph) else text, style)


def _stat_table(pairs, styles):
    # `v`/`k` are almost always internally-computed (counts, formatted numbers) but are
    # escaped unconditionally rather than trusted by call site — reportlab's Paragraph
    # interprets its text as markup (<b>, <font>, <a href>, <img src>), and every OTHER
    # place this module builds a Paragraph from external-feed-derived text (team/league
    # names, ultimately from Betwinner's own feed) escapes first. One unescaped path is
    # one path a future caller can wire feed text through without anyone noticing.
    rows = [[Paragraph(f"<b>{_esc(v)}</b>", styles["Card"]), Paragraph(_esc(k), styles["Small"])]
           for k, v in pairs]
    # Two stats per physical row, side by side.
    grid = []
    for i in range(0, len(rows), 2):
        pair = rows[i:i + 2]
        if len(pair) == 1:
            pair.append(["", ""])
        grid.append([pair[0][0], pair[0][1], pair[1][0], pair[1][1]])
    t = Table(grid, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _title_block(story, styles, c):
    story.append(_p("Günlük Kombine Raporu", styles["H1"]))
    story.append(_p(f'Futbol + Tenis · {c.get("date", "—")} · '
                    f'üretildi {str(c.get("generated_at", ""))[:16].replace("T", " ")}',
                    styles["Sub"]))
    story.append(HRFlowable(width="100%", color=LINE, thickness=0.8, spaceBefore=6,
                            spaceAfter=10))


def _no_combine_report(c, styles):
    story = []
    _title_block(story, styles, c)
    story.append(_p("SONUÇ: Bugün için uygun kombine bulunamadı", styles["H2"]))
    story.append(_p(c.get("why") or "Kalite kriterlerini karşılayan seçim çıkmadı.",
                    styles["Body"]))
    story.append(Spacer(1, 8))
    story.append(_stat_table([
        ("Taranan maç", c.get("scanned_count", "—")),
        ("Eşiği geçen aday", c.get("eligible_count", "—")),
        ("Hakem kurulu onayı", c.get("referee_approved_count", "—")),
        ("Minimum kombin güveni", f'{c.get("min_combine_confidence", "—")}/100'),
    ], styles))
    if c.get("gate_excluded"):
        story.append(_p("Elenen adaylar ve gerekçeleri", styles["H2"]))
        rows = [["Maç", "Neden"]]
        for g in c["gate_excluded"][:40]:
            rows.append([g["match"], "; ".join(g["reasons"])])
        story.append(_wrapped_table(rows, styles, [55 * mm, 115 * mm]))
    if c.get("vetoed"):
        story.append(_p("Hakem kurulu tarafından veto edilenler", styles["H2"]))
        rows = [["Maç", "Veto gerekçesi"]]
        for v in c["vetoed"][:40]:
            rows.append([v["match"], "; ".join(v["vetoes"])])
        story.append(_wrapped_table(rows, styles, [55 * mm, 115 * mm]))
    story.append(Spacer(1, 14))
    story.append(_p("Hiçbir istatistiksel model kesin kazanç sağlamaz. Kombine "
                    "üretilmemesi, ürünün kalite eşiklerini korumasının bir sonucudur — "
                    "eksik veri asla uydurulmaz.", styles["Warn"]))
    return story


def _wrapped_table(rows, styles, col_widths):
    # Every cell here can be feed-derived (match names built from Betwinner's own O1/O2 —
    # engine/bwfeed.py — flow into these tables via combine.json's gate_excluded/vetoed/
    # borderline lists). MUST be escaped before reaching Paragraph, which interprets its
    # text as markup — an unescaped `<font size="40">...</font>` or `<a href="...">` in a
    # crafted team/tournament name would render as attacker-controlled styling/links in a
    # PDF generated unattended and delivered straight to the operator as an official
    # document. Same class of bug tests/test_combine_platform.py already guards against
    # for the HTML pages (test_combine_page_escapes_hostile_team_names); this closes the
    # equivalent gap in the PDF path.
    data = [[Paragraph(_esc(cell), styles["Small"] if r else styles["Card"])
            for cell in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _combine_report(c, styles):
    story = []
    _title_block(story, styles, c)
    story.append(_stat_table([
        ("Seçim sayısı", c["leg_count"]),
        ("Toplam oran", _fmt_num(c.get("combined_odds"))),
        ("Ortalama güven", f'{_fmt_num(c.get("avg_confidence"), 1)}/100'),
        ("Birleşik başarı tahmini", _fmt_pct(c.get("combined_probability"))),
    ], styles))
    band = c.get("combined_probability_band") or {}
    story.append(Spacer(1, 4))
    story.append(_p(f"Güven aralığı (kaba tahmin): {_fmt_pct(band.get('low'))} – "
                    f"{_fmt_pct(band.get('high'))} · taranan {c.get('scanned_count','—')} "
                    f"maç, {c.get('eligible_count','—')} eşiği geçti, "
                    f"{c.get('referee_approved_count','—')} hakem onayı aldı",
                    styles["Small"]))
    if c.get("coupon_code"):
        story.append(Spacer(1, 6))
        story.append(_p(f'<b>Kupon kodu: {c["coupon_code"]}</b> — Betwinner’da '
                        f'"Kuponu yükle" kutusuna elle girin ({c.get("coupon_detail","")}). '
                        'KOMBİNE olarak yüklenir.', styles["Body"]))

    story.append(_p("Seçimler", styles["H2"]))
    for i, leg in enumerate(c["legs"], 1):
        story.extend(_leg_block(i, leg, styles))

    if c.get("borderline"):
        story.append(PageBreak())
        story.append(_p("Sınırda kalan seçimler (kombine dışı)", styles["H2"]))
        story.append(_p("Birleşik olasılığı ürünün anlamlı kabul ettiği eşiğin altına "
                        "düşürmemek için dışarıda bırakıldı.", styles["Small"]))
        rows = [["Maç", "Güven"]]
        for b in c["borderline"][:30]:
            rows.append([b["match"], f'{_fmt_num(b["confidence"], 1)}'])
        story.append(_wrapped_table(rows, styles, [130 * mm, 40 * mm]))

    if c.get("vetoed"):
        story.append(_p("Veto edilen adaylar", styles["H2"]))
        rows = [["Maç", "Gerekçe"]]
        for v in c["vetoed"][:30]:
            rows.append([v["match"], "; ".join(v["vetoes"])])
        story.append(_wrapped_table(rows, styles, [55 * mm, 115 * mm]))

    story.append(Spacer(1, 16))
    story.append(_p("Sorumlu kullanım uyarısı", styles["H2"]))
    story.append(_p(
        "Bu rapor kişisel karar desteği amaçlıdır. Hiçbir istatistiksel model kesin "
        "kazanç sağlamaz; geçmiş başarı gelecekteki başarının garantisi değildir. "
        "Yüksek seçim sayısı birleşik başarı ihtimalini ciddi biçimde düşürebilir. "
        "Bahis miktarı, gerçek para veya kasa yönetimi bu platformda takip edilmez — "
        "yalnızca analiz ve karar desteği sunulur. Kupon otomatik olarak yatırılmaz.",
        styles["Warn"]))
    return story


def _leg_block(i, leg, styles):
    conf = leg.get("confidence") or {}
    dq = conf.get("data_quality") or {}
    ref = leg.get("referee") or {}
    out = [_p(f'#{i}  {leg["match"]} — {leg.get("selection_tr", leg.get("selection"))}',
             styles["Card"])]
    out.append(_p(f'{leg.get("sport")} · {leg.get("league")} · {leg.get("start", "")} · '
                  f'oran {_fmt_num(leg.get("odds"))} · güven '
                  f'{_fmt_num(conf.get("confidence_score"), 1)}/100 · '
                  f'veri kalitesi {dq.get("score", "—")}/100', styles["Small"]))
    factors = conf.get("factors") or {"up": [], "down": []}
    if factors["up"]:
        out.append(_p("Güveni artıran: " + "; ".join(factors["up"]), styles["Body"]))
    if factors["down"]:
        out.append(_p("Güveni azaltan: " + "; ".join(factors["down"]), styles["Body"]))
    if conf.get("risks"):
        out.append(_p("Riskler: " + "; ".join(conf["risks"]), styles["Body"]))
    judges = ", ".join(f'{v["judge"]}: {v["verdict"].upper()}'
                       for v in ref.get("verdicts", []))
    if judges:
        out.append(_p("Hakem kurulu: " + judges, styles["Small"]))
    out.append(Spacer(1, 8))
    out.append(HRFlowable(width="100%", color=LINE, thickness=0.4, spaceAfter=8))
    return out


def build(input_path, out_path):
    with open(input_path) as f:
        c = json.load(f)
    _register_fonts()
    styles = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title="Günlük Kombine Raporu")
    story = _combine_report(c, styles) if c.get("leg_count", 0) > 0 \
        else _no_combine_report(c, styles)
    doc.build(story)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="combine.json")
    ap.add_argument("--out", default="combine_report.pdf")
    args = ap.parse_args()
    if not os.path.exists(args.input):
        print(f"{args.input} not found — run tools/daily_combine.py first", file=sys.stderr)
        return 1
    path = build(args.input, args.out)
    print(f"wrote {path} ({os.path.getsize(path)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
