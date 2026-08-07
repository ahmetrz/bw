#!/usr/bin/env python3
"""Render every new combine-platform screen from combine.json / data/combine_log.jsonl /
data/proposed_changes.jsonl / data/source_health.json / data/predictions.jsonl.

    python tools/make_platform_pages.py

One process, one pass: every screen is generated from whatever data exists right now, so
a page is never half-updated relative to another. Does not touch picks.html/results.html/
stats.html/method.html — those are tools/daily_report.py's and tools/daily_results.py's,
unchanged (docs/DECISIONS/0001).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import governance, track_record  # noqa: E402
from tools import webshell as ws  # noqa: E402
from tools.grade_predictions import load_jsonl  # noqa: E402

REFEREE_JUDGE_LABELS = {
    "veri_kalitesi": "Veri Kalitesi Hakemi", "istatistiksel_tutarlilik": "İstatistiksel Tutarlılık Hakemi",
    "pazar_guvenilirligi": "Pazar Güvenilirliği Hakemi", "overfitting": "Overfitting Hakemi",
    "guncellik": "Haber ve Güncellik Hakemi", "korelasyon": "Korelasyon ve Ortak Risk Hakemi",
    "oran_ev": "Oran/EV Hakemi", "gecmis_performans": "Geçmiş Performans Hakemi",
    "sonuc_dogrulanabilirligi": "Sonuç Doğrulanabilirliği Hakemi", "nihai_risk": "Nihai Risk Hakemi",
}


def _load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------------------- combine.html

def _bw_link(url):
    if not url:
        return ""
    return (f'<div class="small" style="margin-top:6px"><a href="{ws.esc(url)}" '
           f'target="_blank" rel="noopener">Betwinner’a git ↗</a></div>')


def _coupon_block(c):
    if not c.get("coupon_code"):
        return ('<div class="small muted" style="margin-top:6px">Kupon kodu üretilmedi '
               '(--no-coupon veya API erişilemedi).</div>')
    detail = ws.esc(c.get("coupon_detail", ""))
    return (f'<div class="card" style="margin-top:10px;background:var(--panel2)">'
           f'<b>Kupon kodu:</b> <span class="mono">{ws.esc(c["coupon_code"])}</span>'
           f'<div class="small muted">{detail} — Betwinner’da “Kuponu yükle” kutusuna '
           f'elle girin; KOMBİNE olarak yüklenir.</div></div>')


def render_combine(c):
    if not c or c.get("leg_count", 0) == 0:
        why = (c or {}).get("why") or "bugün için veri henüz üretilmedi"
        body = ws.empty_state(
            f'Bugün kalite kriterlerini karşılayan uygun kombine bulunamadı. {ws.esc(why)}')
        if c:
            body += f"""<div class="card">
              <h2 style="margin-top:0">Tarama özeti</h2>
              <div class="grid">
                {ws.stat("Taranan maç", c.get("scanned_count", "—"))}
                {ws.stat("Eşiği geçen", c.get("eligible_count", "—"))}
                {ws.stat("Hakem onaylı", c.get("referee_approved_count", "—"))}
              </div></div>"""
        return ws.page("Bugünün Kuponu", "combine.html", body,
                       subtitle="Kupon bulunamadı durumu")

    legs_html = ""
    for i, leg in enumerate(c["legs"], 1):
        conf = leg.get("confidence") or {}
        dq = conf.get("data_quality") or {}
        ref = leg.get("referee") or {}
        factors = conf.get("factors") or {"up": [], "down": []}
        up = "".join(f'<div class="small">▲ {ws.esc(f)}</div>' for f in factors["up"])
        down = "".join(f'<div class="small">▼ {ws.esc(f)}</div>' for f in factors["down"])
        risks = "".join(f'<li>{ws.esc(r)}</li>' for r in (conf.get("risks") or []))
        judge_badges = "".join(
            f'<span class="badge {v["verdict"]}" title="{ws.esc(v["note"])}">'
            f'{ws.esc(REFEREE_JUDGE_LABELS.get(v["judge"], v["judge"]))}</span> '
            for v in (ref.get("verdicts") or []))
        legs_html += f"""
        <details class="card" {"open" if i <= 3 else ""}>
          <summary><b>#{i} {ws.esc(leg["match"])}</b> — {ws.esc(leg.get("selection_tr"))}
            <span class="pill mono">oran {ws.fmt_num(leg.get("odds"))}</span>
            <span class="pill mono">güven {ws.fmt_num(conf.get("confidence_score"), 1)}/100</span>
          </summary>
          <div class="small muted">{ws.esc(leg.get("sport"))} · {ws.esc(leg.get("league"))} ·
            {ws.esc(leg.get("start"))}</div>
          <h2>Analiz</h2>
          <div class="grid">
            {ws.stat("Tahmini olasılık", ws.fmt_pct(conf.get("estimated_probability")))}
            {ws.stat("Implied probability", ws.fmt_pct(conf.get("implied_probability")))}
            {ws.stat("EV (bilgi amaçlı)", ws.fmt_pct(conf.get("expected_value")) if conf.get("expected_value") is not None else "—")}
            {ws.stat("Veri kalitesi", f'{dq.get("score", "—")}/100')}
            {ws.stat("Model sürümü", conf.get("model_version"))}
          </div>
          <div style="margin-top:10px">{up}{down}</div>
          {"<h2>Riskler</h2><ul>" + risks + "</ul>" if risks else ""}
          <h2>Hakem kurulu</h2>
          <div>{judge_badges}</div>
          <div class="small muted" style="margin-top:6px">
            {ws.esc((leg.get("settlement") or {}).get("scope", "sonuçlanma kapsamı: belirtilmedi"))}
            {" · sonuçlanma kuralı teyit edilmedi" if (leg.get("settlement") or {}).get("needs_confirmation") else ""}
          </div>
          {_bw_link(leg.get("url"))}
        </details>"""

    lo_hi = c.get("combined_probability_band") or {}
    body = f"""
    <div class="card">
      <div class="grid">
        {ws.stat("Kupon durumu", "OLUŞTURULDU")}
        {ws.stat("Oluşturulma", c.get("generated_at", "—")[:16].replace("T", " "))}
        {ws.stat("Seçim sayısı", c["leg_count"])}
        {ws.stat("Toplam oran", ws.fmt_num(c.get("combined_odds")))}
        {ws.stat("Ortalama güven", ws.fmt_num(c.get("avg_confidence"), 1))}
        {ws.stat("Birleşik başarı tahmini", ws.fmt_pct(c.get("combined_probability")))}
      </div>
      <div class="small muted" style="margin-top:10px">
        Güven aralığı (kaba tahmin): {ws.fmt_pct(lo_hi.get("low"))} – {ws.fmt_pct(lo_hi.get("high"))}
        · minimum kombin güveni: {c.get("min_combine_confidence", "—")}/100
        · tarama: {c.get("scanned_count", "—")} maç, {c.get("eligible_count", "—")} eşiği geçti,
        {c.get("referee_approved_count", "—")} hakem onayı aldı
      </div>
      {_coupon_block(c)}
      <div class="small muted" style="margin-top:10px"><i>{ws.esc(c.get("why", ""))}</i></div>
    </div>
    <h2>Seçimler</h2>
    {legs_html}
    """
    if c.get("borderline"):
        body += "<h2>Sınırda kalan seçimler</h2><div class=\"card\"><ul>" + "".join(
            f'<li>{ws.esc(b["match"])} — güven {ws.fmt_num(b["confidence"], 1)}</li>'
            for b in c["borderline"]) + "</ul></div>"
    return ws.page("Bugünün Kuponu", "combine.html", body,
                   subtitle=f'Futbol + Tenis · {c.get("date", "")}')


# ---------------------------------------------------------------------------- referee.html

def render_referee(c):
    if not c or not c.get("legs"):
        extra = ""
        if c and c.get("vetoed"):
            rows = "".join(
                f'<tr><td>{ws.esc(v["match"])}</td><td>{"<br>".join(ws.esc(x) for x in v["vetoes"])}</td></tr>'
                for v in c["vetoed"])
            extra = f'<h2>Veto edilen adaylar</h2><div class="tablewrap"><table>' \
                    f'<tr><th>Maç</th><th>Veto gerekçesi</th></tr>{rows}</table></div>'
        return ws.page("Hakem Kurulu", "referee.html",
                       ws.empty_state("Bugün değerlendirilecek onaylı seçim yok.") + extra)
    rows = ""
    for leg in c["legs"]:
        ref = leg.get("referee") or {}
        for v in ref.get("verdicts", []):
            rows += (f'<tr><td>{ws.esc(leg["match"])}</td>'
                    f'<td>{ws.esc(REFEREE_JUDGE_LABELS.get(v["judge"], v["judge"]))}</td>'
                    f'<td><span class="badge {v["verdict"]}">{ws.esc(v["verdict"].upper())}</span></td>'
                    f'<td>{ws.esc(v.get("reason_code") or "—")}</td>'
                    f'<td class="small">{ws.esc(v["note"])}</td></tr>')
    body = f"""<div class="tablewrap"><table>
      <tr><th>Maç</th><th>Hakem</th><th>Karar</th><th>Neden kodu</th><th>Not</th></tr>
      {rows}
    </table></div>"""
    if c.get("vetoed"):
        body += "<h2>Veto edilen adaylar</h2><div class=\"tablewrap\"><table><tr><th>Maç</th><th>Gerekçe</th></tr>" + \
            "".join(f'<tr><td>{ws.esc(v["match"])}</td><td>{"<br>".join(ws.esc(x) for x in v["vetoes"])}</td></tr>'
                    for v in c["vetoed"]) + "</table></div>"
    if c.get("correlation_notes"):
        body += "<h2>Korelasyon notları</h2><div class=\"card\"><ul>" + \
            "".join(f'<li>{ws.esc(n)}</li>' for n in c["correlation_notes"]) + "</ul></div>"
    return ws.page("Hakem Kurulu", "referee.html", body,
                   subtitle="On bağımsız, kural tabanlı hakem — harici yapay zeka kullanılmaz")


# ------------------------------------------------------------------------- dataquality.html

def render_dataquality(c):
    if not c or not c.get("legs"):
        return ws.page("Veri Kalitesi", "dataquality.html",
                       ws.empty_state("Bugün için seçim yok."))
    rows = ""
    for leg in c["legs"]:
        dq = (leg.get("confidence") or {}).get("data_quality") or {}
        reasons = "<br>".join(
            f'<span class="badge {r["severity"]}">{ws.esc(r["code"])}</span> {ws.esc(r["detail"])}'
            for r in dq.get("reasons", []) if r["severity"] != "info")
        rows += (f'<tr><td>{ws.esc(leg["match"])}</td><td class="mono">{dq.get("score","—")}</td>'
                f'<td class="small">{reasons or "—"}</td></tr>')
    body = f"""<div class="tablewrap"><table>
      <tr><th>Maç</th><th>Puan</th><th>Bulgular</th></tr>{rows}
    </table></div>
    <h2>Yapısal sınırlamalar (her seçimde geçerli)</h2>
    <div class="card small">
      Bu platform kadro/sakatlık verisi ve çapraz kaynak doğrulaması için ayrı bir kaynak
      entegre etmiyor — tek oran kaynağı (Betwinner) kullanılıyor. Bu, her seçimde
      <span class="badge info">LINEUP_DATA_UNAVAILABLE</span> ve
      <span class="badge info">SOURCE_CONFLICT</span> olarak açıkça bildirilir; puana
      dahil edilmez, yalnızca bilgi amaçlıdır.
    </div>"""
    return ws.page("Veri Kalitesi", "dataquality.html", body)


# ---------------------------------------------------------------------------- scanned.html

def render_scanned(c):
    if not c:
        return ws.page("Taranan Karşılaşmalar", "scanned.html", ws.empty_state("Veri yok."))
    body = f"""<div class="card"><div class="grid">
        {ws.stat("Taranan maç", c.get("scanned_count", "—"))}
        {ws.stat("Eşiği geçen", c.get("eligible_count", "—"))}
        {ws.stat("Hakem onaylı", c.get("referee_approved_count", "—"))}
        {ws.stat("Kupona giren", c.get("leg_count", 0))}
    </div></div>"""
    if c.get("gate_excluded"):
        rows = "".join(
            f'<tr><td>{ws.esc(g["match"])}</td><td class="small">{"<br>".join(ws.esc(r) for r in g["reasons"])}</td></tr>'
            for g in c["gate_excluded"])
        body += f'<h2>Eşiği geçemeyenler</h2><div class="tablewrap"><table><tr><th>Maç</th><th>Neden</th></tr>{rows}</table></div>'
    else:
        body += ws.empty_state("Bugün eşik dışı kalan maç yok.")
    return ws.page("Taranan Karşılaşmalar", "scanned.html", body)


# --------------------------------------------------------------------------- rejected.html

def render_rejected(c):
    if not c or not (c.get("vetoed") or c.get("borderline") or c.get("gate_excluded")):
        return ws.page("Elenen Seçimler", "rejected.html",
                       ws.empty_state("Bugün için eleme kaydı yok."))
    body = ""
    if c.get("vetoed"):
        rows = "".join(
            f'<tr><td>{ws.esc(v["match"])}</td><td class="small">{"<br>".join(ws.esc(x) for x in v["vetoes"])}</td></tr>'
            for v in c["vetoed"])
        body += f'<h2>Hakem kurulu tarafından veto edildi</h2><div class="tablewrap"><table><tr><th>Maç</th><th>Gerekçe</th></tr>{rows}</table></div>'
    if c.get("borderline"):
        rows = "".join(f'<tr><td>{ws.esc(b["match"])}</td><td class="mono">{ws.fmt_num(b["confidence"],1)}</td></tr>'
                       for b in c["borderline"])
        body += f'<h2>Onaylandı ama kombine seçilmedi</h2><div class="small muted">Birleşik olasılığı ürünün anlamlı kabul ettiği eşiğin altına düşürmemek için dışarıda bırakıldı.</div><div class="tablewrap"><table><tr><th>Maç</th><th>Güven</th></tr>{rows}</table></div>'
    if c.get("gate_excluded"):
        rows = "".join(
            f'<tr><td>{ws.esc(g["match"])}</td><td class="small">{"<br>".join(ws.esc(r) for r in g["reasons"])}</td></tr>'
            for g in c["gate_excluded"])
        body += f'<h2>Giriş eşiği geçilemedi</h2><div class="tablewrap"><table><tr><th>Maç</th><th>Neden</th></tr>{rows}</table></div>'
    return ws.page("Elenen Seçimler", "rejected.html", body)


# ------------------------------------------------------------- combine_history.html / results

def render_combine_history(rows, focus):
    rows = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)
    if focus == "results":
        rows = [r for r in rows if r.get("settlement")]
    if not rows:
        msg = "Henüz sonuçlanmış kombine yok." if focus == "results" else "Henüz kombine geçmişi yok."
        return ws.page("Sonuçlar" if focus == "results" else "Geçmiş Kuponlar",
                       "combine_results.html" if focus == "results" else "combine_history.html",
                       ws.empty_state(msg))
    trs = ""
    for r in rows:
        s = r.get("settlement")
        if s is None:
            badge = '<span class="badge pending">BEKLİYOR</span>'
        elif s["result"] == "no_bet":
            badge = '<span class="badge pending">KUPON YOK</span>'
        elif s["result"] == "win":
            badge = f'<span class="badge win">KAZANDI ×{ws.fmt_num(s["multiplier"])}</span>'
        else:
            badge = '<span class="badge loss">KAYBETTİ</span>'
        trs += (f'<tr><td>{ws.esc(r.get("date"))}</td><td class="mono">{r.get("leg_count",0)}</td>'
               f'<td class="mono">{ws.fmt_num(r.get("combined_odds"))}</td>'
               f'<td class="mono">{ws.fmt_pct(r.get("combined_probability"))}</td>'
               f'<td>{badge}</td></tr>')
    body = f"""<div class="tablewrap"><table>
      <tr><th>Tarih</th><th>Seçim</th><th>Toplam Oran</th><th>Tahmini Olasılık</th><th>Sonuç</th></tr>
      {trs}
    </table></div>"""
    title = "Sonuçlar" if focus == "results" else "Geçmiş Kuponlar"
    href = "combine_results.html" if focus == "results" else "combine_history.html"
    return ws.page(title, href, body)


# ---------------------------------------------------------------------------------- lab.html

def render_lab(brier, logloss, calib, market_hist):
    cards = f"""<div class="card"><div class="grid">
        {ws.stat("Brier score (genel)", ws.fmt_num((brier or {}).get("overall")) if brier else "—")}
        {ws.stat("Log loss (genel)", ws.fmt_num(logloss) if logloss is not None else "—")}
        {ws.stat("Notlandırılmış seçim", (brier or {}).get("n", "—") if brier else "—")}
    </div>
    <div class="small muted" style="margin-top:8px">Düşük Brier/log-loss daha iyidir.
      Referans: sabit %50 tahmin Brier=0.25, log-loss=0.693. ROI yalnızca analitik bir
      metriktir — gerçek para takibi yapılmaz.</div></div>"""

    sport_rows = ""
    for sid, s in sorted((brier or {}).get("by_sport", {}).items() or []):
        sport_rows += f'<tr><td>{ws.esc(sid)}</td><td class="mono">{ws.fmt_num(s)}</td></tr>'
    sport_table = (f'<h2>Spor bazlı Brier score</h2><div class="tablewrap"><table>'
                   f'<tr><th>Spor</th><th>Brier</th></tr>{sport_rows}</table></div>'
                   if sport_rows else "")

    calib_rows = ""
    for sid, b in sorted((calib or {}).items()):
        gap = b["claimed"] - b["realised"]
        flag = '<span class="badge bad">FARK</span>' if abs(gap) > 0.05 else '<span class="badge ok">UYUMLU</span>'
        calib_rows += (f'<tr><td>{ws.esc(sid)}</td><td class="mono">{ws.fmt_pct(b["claimed"])}</td>'
                       f'<td class="mono">{ws.fmt_pct(b["realised"])}</td><td class="mono">{gap*100:+.1f}</td>'
                       f'<td>{flag}</td><td class="mono">{b["graded"]}</td></tr>')
    calib_table = (f'<h2>İddia edilen vs gerçekleşen (spor bazlı)</h2><div class="tablewrap"><table>'
                   f'<tr><th>Spor</th><th>İddia</th><th>Gerçekleşen</th><th>Fark (puan)</th><th></th><th>Örneklem</th></tr>'
                   f'{calib_rows}</table></div>' if calib_rows else
                   ws.empty_state("Kalibrasyon için henüz yeterli notlandırılmış seçim yok "
                                  f"(<{track_record.MIN_MEANINGFUL})."))

    market_rows = "".join(
        f'<tr><td>{ws.esc(mt)}</td><td class="mono">{h["graded"]}</td>'
        f'<td class="mono">{ws.fmt_pct(h["ungradeable_rate"])}</td></tr>'
        for mt, h in sorted((market_hist or {}).items()))
    market_table = (f'<h2>Pazar bazlı doğrulanabilirlik</h2><div class="tablewrap"><table>'
                    f'<tr><th>Pazar</th><th>Değerlendirilen</th><th>Notlandırılamayan oran</th></tr>'
                    f'{market_rows}</table></div>' if market_rows else "")

    return ws.page("Performans Laboratuvarı", "lab.html",
                   cards + sport_table + calib_table + market_table)


# --------------------------------------------------------------------------- calibration.html

def render_calibration(calib):
    if not calib:
        return ws.page("Güven Kalibrasyonu", "calibration.html",
                       ws.empty_state(f"Henüz yeterli notlandırılmış seçim yok "
                                     f"(<{track_record.MIN_MEANINGFUL} spor başına)."))
    rows = ""
    for sid, b in sorted(calib.items()):
        gap = b["claimed"] - b["realised"]
        rows += (f'<tr><td>{ws.esc(sid)}</td><td class="mono">{ws.fmt_pct(b["claimed"])}</td>'
                f'<td class="mono">{ws.fmt_pct(b["realised"])}</td>'
                f'<td class="mono">{gap*100:+.1f} puan</td><td class="mono">{b["graded"]}</td></tr>')
    body = f"""<div class="small muted">Bu tablo modelin YANLIŞ olduğunu söyleyebilen tek
      tablodur — şanssızlık değil. İddia edilen olasılık, güven puanının ima ettiği
      kazanma oranıdır; gerçekleşen, notlandırılmış seçimlerin fiili isabet oranıdır.</div>
      <div class="tablewrap" style="margin-top:10px"><table>
      <tr><th>Spor</th><th>İddia edilen</th><th>Gerçekleşen</th><th>Fark</th><th>Örneklem</th></tr>
      {rows}</table></div>"""
    return ws.page("Güven Kalibrasyonu", "calibration.html", body)


# ----------------------------------------------------------------------- model_versions.html

def render_model_versions(sport_ids):
    body = ""
    any_versions = False
    for sid in sorted(sport_ids):
        versions = governance.list_model_versions(sid)
        if not versions:
            continue
        any_versions = True
        rows = "".join(f'<tr><td>{ws.esc(v["archived_at"][:16].replace("T"," "))}</td>'
                       f'<td class="mono">{ws.esc(v["file"])}</td></tr>'
                       for v in sorted(versions, key=lambda v: v["archived_at"], reverse=True))
        body += f'<h2>Spor {sid}</h2><div class="tablewrap"><table><tr><th>Arşivlenme</th><th>Dosya</th></tr>{rows}</table></div>'
    if not any_versions:
        body = ws.empty_state("Henüz arşivlenmiş model sürümü yok — ilk günlük yeniden "
                              "eğitimden sonra burada listelenecek.")
    body += ('<div class="card small" style="margin-top:14px">Her günlük yeniden eğitim '
            'öncesi mevcut model sürümü değiştirilemez biçimde arşivlenir '
            '(engine/governance.archive_model_version). Rutin yeniden eğitim otomatiktir '
            've yalnızca kendi tuttuğu kalibrasyon kontrolünden geçerse üretime girer '
            '(bkz. docs/DECISIONS/0004) — yapısal değişiklikler ayrı onay sürecinden geçer.</div>')
    return ws.page("Model Sürümleri", "model_versions.html", body)


# ------------------------------------------------------------------- proposed_changes.html

def render_proposed_changes(proposals):
    if not proposals:
        return ws.page("Önerilen Model Değişiklikleri", "proposed_changes.html",
                       ws.empty_state("Bekleyen öneri yok."))
    rows = ""
    for p in proposals:
        badge = {"proposed": "warn", "approved": "ok", "rejected": "bad"}.get(p["status"], "pending")
        rows += f"""<details class="card">
          <summary><span class="badge {badge}">{ws.esc(p["status"].upper())}</span>
            <b>{ws.esc(p["title"])}</b>
            <span class="small muted">({ws.esc(p["category"])}, {ws.esc(p["created_at"][:10])})</span>
          </summary>
          <p class="small">{ws.esc(p["description"])}</p>
          <div class="small"><b>Mevcut değer:</b> <span class="mono">{ws.esc(p.get("current_value"))}</span></div>
          <div class="small"><b>Önerilen değer:</b> <span class="mono">{ws.esc(p.get("proposed_value"))}</span></div>
          <details><summary class="small">Kanıt</summary>
            <pre class="small mono" style="white-space:pre-wrap">{ws.esc(json.dumps(p.get("evidence"), ensure_ascii=False, indent=2))}</pre>
          </details>
          {f'<div class="small muted">İnceleyen: {ws.esc(p.get("reviewed_by"))} — {ws.esc(p.get("review_note") or "")}</div>' if p.get("reviewed_by") else '<div class="small muted">İnsan onayı bekliyor. Hiçbir kod bu öneriyi otomatik uygulamaz.</div>'}
        </details>"""
    return ws.page("Önerilen Model Değişiklikleri", "proposed_changes.html", rows,
                   subtitle="İnsan onayı olmadan hiçbir üretim modeli, eşik veya kural değişmez")


# --------------------------------------------------------------------- source_health.html

def render_source_health(health):
    if not health:
        return ws.page("Veri Kaynağı Sağlığı", "source_health.html",
                       ws.empty_state("Henüz sağlık kontrolü çalıştırılmadı — "
                                     "python tools/check_source_health.py"))
    rows = ""
    for s in health.get("sources", []):
        badge = {"ok": "ok", "degraded": "warn", "unavailable": "bad"}.get(s["state"], "pending")
        rows += (f'<tr><td>{ws.esc(s["name"])}</td><td>{ws.esc(s["category"])}</td>'
                f'<td><span class="badge {badge}">{ws.esc(s["state"].upper())}</span></td>'
                f'<td class="mono">{ws.esc(s.get("http_status"))}</td>'
                f'<td class="small">{ws.esc(s.get("checked_at",""))[:16].replace("T"," ")}</td></tr>')
    body = f"""<div class="small muted">Son çalıştırma: {ws.esc(health.get("checked_at",""))[:16].replace("T"," ")}
      · Her kaynak GÖVDE üzerinden doğrulanır, yalnızca HTTP durum koduyla değil
      (bkz. CLAUDE.md sert kural 10) — bir kaynak 200 dönüp yine de "degraded"
      işaretlenebilir.</div>
      <div class="tablewrap" style="margin-top:10px"><table>
      <tr><th>Kaynak</th><th>Kategori</th><th>Durum</th><th>HTTP</th><th>Kontrol</th></tr>
      {rows}</table></div>
      <div class="small muted" style="margin-top:10px">Tam katalog: docs/DATA_SOURCES.md</div>"""
    return ws.page("Veri Kaynağı Sağlığı", "source_health.html", body)


# --------------------------------------------------------------------------------- runs.html

def render_runs(combine_rows, watch_rows):
    combine_rows = sorted(combine_rows, key=lambda r: r.get("generated_at", ""), reverse=True)[:30]
    crows = "".join(
        f'<tr><td>{ws.esc(r.get("generated_at",""))[:16].replace("T"," ")}</td>'
        f'<td class="mono">{r.get("leg_count",0)}</td>'
        f'<td class="mono">{ws.esc(r.get("config_fingerprint"))}</td></tr>'
        for r in combine_rows)
    body = f'<h2>Günlük kombine çalıştırmaları</h2><div class="tablewrap"><table>' \
          f'<tr><th>Zaman</th><th>Seçim</th><th>Yapılandırma</th></tr>{crows}</table></div>' \
          if crows else ws.empty_state("Henüz kombine çalıştırması yok.")
    if watch_rows:
        recent = watch_rows[-20:]
        wrows = "".join(f'<tr><td>{ws.esc(w.get("at"))}</td><td class="mono">{w.get("sport")}</td>'
                        f'<td class="mono">{w.get("added",0)}</td></tr>' for w in reversed(recent))
        body += f'<h2>Canlı izleyici (son taramalar)</h2><div class="tablewrap"><table>' \
               f'<tr><th>Zaman</th><th>Spor</th><th>Eklenen sonuç</th></tr>{wrows}</table></div>'
    return ws.page("Sistem Çalışma Geçmişi", "runs.html", body)


# ----------------------------------------------------------------------------- settings.html

def render_settings():
    import config
    rows = ""
    keys = ["MIN_ODDS", "MIN_MODEL_SURVIVAL", "ALLOW_PUSH_MARKETS", "DAILY_WINDOWS_HOURS",
           "EXCLUDED_SPORTS", "COMBINE_SPORTS", "MIN_COMBINE_CONFIDENCE",
           "MIN_COMBINE_COMBINED_PROBABILITY", "COMBINE_BEAM_WIDTH",
           "COMBINE_MAX_LEAGUE_SHARE"]
    for k in keys:
        v = getattr(config, k, None)
        v = sorted(v) if isinstance(v, (set, frozenset)) else v
        rows += f'<tr><td class="mono">{ws.esc(k)}</td><td class="mono">{ws.esc(v)}</td></tr>'
    body = f"""<div class="small muted">Salt okunur görünüm — bu platformda canlı bir ayar
      arayüzü yoktur. Değişiklikler config.py düzenlenerek ve gözden geçirilerek yapılır;
      yapısal değişiklikler önce "Önerilen Model Değişiklikleri" ekranından geçer.</div>
      <div class="tablewrap" style="margin-top:10px"><table>
      <tr><th>Ayar</th><th>Değer</th></tr>{rows}</table></div>"""
    return ws.page("Ayarlar", "settings.html", body)


# --------------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combine", default="combine.json")
    ap.add_argument("--combine-log", default="data/combine_log.jsonl")
    ap.add_argument("--source-health", default="data/source_health.json")
    ap.add_argument("--watch-log", default="data/watch_log.jsonl")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    c = _load_json(args.combine)
    log_rows = load_jsonl(args.combine_log)
    proposals = governance.list_proposals()
    health = _load_json(args.source_health)
    watch_rows = load_jsonl(args.watch_log)

    calib = track_record.calibration_by_sport()
    brier = track_record.brier_score()
    logloss = track_record.log_loss()
    market_hist = track_record.market_history()

    sport_ids = set()
    if c:
        sport_ids |= {leg.get("sport_id") for leg in c.get("legs", [])}
    sport_ids |= {1, 4}

    pages = {
        "combine.html": render_combine(c),
        "referee.html": render_referee(c),
        "dataquality.html": render_dataquality(c),
        "scanned.html": render_scanned(c),
        "rejected.html": render_rejected(c),
        "combine_history.html": render_combine_history(log_rows, "history"),
        "combine_results.html": render_combine_history(log_rows, "results"),
        "lab.html": render_lab(brier, logloss, calib, market_hist),
        "calibration.html": render_calibration(calib),
        "model_versions.html": render_model_versions(sport_ids),
        "proposed_changes.html": render_proposed_changes(proposals),
        "source_health.html": render_source_health(health),
        "runs.html": render_runs(log_rows, watch_rows),
        "settings.html": render_settings(),
    }
    os.makedirs(args.out_dir, exist_ok=True)
    for name, html in pages.items():
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
