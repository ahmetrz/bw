# Betwinner Football & Tennis Combine Platform

A **single-book, two-sport** decision-support platform for Betwinner. Read `CLAUDE.md`
first — it is the maintained operating brief. This README is a quick-start map.

## What it does

Once a day it either produces **one combine** — a small, referee-reviewed,
multi-objective-optimized accumulator across independent football and tennis matches,
each scored 0–100 with full auditable reasoning — or it says plainly that no combine
cleared the bar that day. Ten deterministic judges (no external LLM) can veto any
selection. No reference book, no "value vs. sharp" claim, no bankroll sizing — full
detail in `CLAUDE.md` and `docs/PRODUCT_VISION.md`; every design decision is recorded in
`docs/DECISIONS/`.

This repo used to also run a second, older product — a multi-sport top-N scanner. It was
retired on 2026-08-07 so the combine platform could be the sole product; see
`docs/DECISIONS/0007` for the full reasoning and exactly what was removed.

## Repo map

```
tools/daily_combine.py     daily run: own fetch, 07:00 Istanbul cron -> combine.json
tools/notify_combine.py    sends combine_report.pdf to Telegram with a short caption
tools/grade_combine.py     settles data/combine_log.jsonl once results are known
tools/refresh_combine.py   rebuilds the bet-slip code hourly from legs not yet started
tools/make_pdf_report.py   combine.json -> combine_report.pdf (needs `pip install -r requirements.txt`)
tools/make_platform_pages.py  the 14 web screens, from combine.json + governance data
tools/webshell.py          shared shell/CSS/escaping for the 14 screens
tools/check_source_health.py  probes catalogued data sources, writes data/source_health.json
engine/                    shared engine — see docs/ARCHITECTURE.md for the full module map
config.py                  gates, thresholds, exclusions, windows — one product's worth
docs/                      see docs/ARCHITECTURE.md for the full documentation index
fixtures/                  real pulls = regression anchors
tests/test_regression.py       shared-engine + integration tests
tests/test_combine_platform.py the platform's own tests (confidence, referee, optimizer, pages, PDF)
.github/workflows/         combine.yml is the daily run (07:00 Istanbul, own fetch);
                            results.yml settles + refreshes the coupon + rebuilds pages
                            hourly; watch-live.yml watches football+tennis live results;
                            tests.yml is the push/PR gate
```

## Running things locally

Full walkthrough: `docs/LOCAL_SETUP.md`. Quick reference:

```bash
python tools/daily_combine.py --input fixtures/sample.json --no-coupon
python tools/make_platform_pages.py           # renders the 14 screens from combine.json
python -m unittest discover -s tests -v

# The PDF needs the one dependency this repo takes
pip install -r requirements.txt
python tools/make_pdf_report.py --input combine.json --out combine_report.pdf
```

`--no-coupon` on `daily_combine.py` is important when testing locally: without it, a
non-empty combine calls Betwinner's live slip-minting API (`engine/coupon.py`).

## What's provisional / resolved

- **Cadence** — resolved: the daily run targets 07:00 Istanbul (`combine.yml`,
  operator-approved). See `docs/GITHUB_ACTIONS.md` and `docs/DECISIONS/0006`.
- **Sport scope** — resolved: fixed at football and tennis (`docs/DECISIONS/0007`), not
  "every sport a model can reach."
- **The tennis calibration split** — resolved: reviewed, approved, and implemented; tennis
  produces picks at a 0.023 held-out calibration gap. See `docs/TENNIS_MODELS.md`.
- **Notifications** — resolved: the existing Telegram bot and channel, reused rather than
  a second setup (`tools/notify_combine.py`).

Pure Python standard library for everything except PDF generation (`reportlab`, pinned in
`requirements.txt`).
