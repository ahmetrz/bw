# Betwinner Odds Scanner + Football/Tennis Combine Platform

This repo now holds **two products** sharing one engine. Read `CLAUDE.md` first — it is
the maintained operating brief for the original, live scanner. This README covers both
products at a glance and how to run each one locally.

## Product 1 — the scanner (live, pre-existing)

A **single-book** scanner. Pulls every open market on Betwinner across the configured
tournaments, scores each selection by within-book cheapness (margin/limit/range), ranks
them, returns the top 50 (`scan.py`). Separately, `tools/daily_report.py` runs once a day:
model gives each match a DIRECTION, a safety ladder converts it to its safest form, one
selection per match, sent to Telegram as `picks.html`. No reference book, no "value vs.
sharp" claim — full detail in `CLAUDE.md`.

## Product 2 — the daily combine platform (added this session)

A **football + tennis only** decision-support layer on top of the same engine. Once a day
it either produces **one combine** — a small, referee-reviewed, multi-objective-optimized
accumulator across independent matches, each scored 0–100 with full auditable reasoning —
or it says plainly that no combine cleared the bar that day. Ten deterministic judges (no
external LLM) can veto any selection. Full reasoning in `docs/PRODUCT_VISION.md` and
`docs/ARCHITECTURE.md`; every design decision is recorded in `docs/DECISIONS/`.

## Repo map

```
scan.py                    Product 1 entrypoint: parse -> filter -> score -> rank -> top-N
tools/daily_report.py      Product 1 daily run: fetch -> pick -> score -> picks.html -> Telegram
tools/daily_combine.py     Product 2 daily run: same card -> combine -> combine.json
tools/grade_combine.py     settles data/combine_log.jsonl once results are known
tools/make_pdf_report.py   combine.json -> combine_report.pdf (needs `pip install -r requirements.txt`)
tools/make_platform_pages.py  the 14 new web screens, from combine.json + governance data
tools/webshell.py          shared shell/CSS/escaping for the 14 new screens (NOT used by the old ones)
tools/check_source_health.py  probes catalogued data sources, writes data/source_health.json
engine/                    shared engine — see docs/ARCHITECTURE.md for the full module map
config.py                  Product 1 config (unchanged) + a clearly-delineated Product 2 section
docs/                      see docs/ARCHITECTURE.md for the full documentation index
fixtures/                  real pulls = regression anchors (Product 1); reused by Product 2's tests
tests/test_regression.py       Product 1's test suite — do not add Product 2 tests here
tests/test_combine_platform.py Product 2's test suite — kept separate on purpose (docs/DECISIONS/0001)
.github/workflows/         daily.yml/results.yml now run BOTH products (same fetch, no double-download);
                            tests.yml is new (push/PR gate — did not exist before this session)
```

## Running things locally

Full walkthrough: `docs/LOCAL_SETUP.md`. Quick reference:

```bash
# Product 1 — no install needed, stdlib only
python scan.py --input fixtures/sample.json
python -m unittest discover -s tests -v      # runs BOTH test files

# Product 2 — no install needed for the pipeline itself
python tools/daily_combine.py --input fixtures/sample.json --no-coupon
python tools/make_platform_pages.py           # renders the 14 new screens from combine.json

# Product 2's PDF needs the one dependency this repo takes
pip install -r requirements.txt
python tools/make_pdf_report.py --input combine.json --out combine_report.pdf
```

`--no-coupon` on `daily_combine.py` is important when testing locally: without it, a
non-empty combine calls Betwinner's live slip-minting API (`engine/coupon.py`).

## What's provisional / needs an operator decision

- **Composite weights** (`config.WEIGHTS`, Product 1) — provisional, tune against real data.
- **Cadence** — Product 2 currently fires on Product 1's existing, operator-approved
  schedule (~09:43 Istanbul), not the platform brief's requested 07:00 Istanbul. See
  `docs/GITHUB_ACTIONS.md` — changing a schedule needs the same approval gate CLAUDE.md's
  HITL 5 already established, so this session did not change it unilaterally.
- **The filed tennis calibration proposal** (`data/proposed_changes.jsonl`,
  `pmc-2026-08-06-tennis-split`) — awaiting review, see `docs/TENNIS_MODELS.md`.

Pure Python standard library for everything except PDF generation (`reportlab`, pinned in
`requirements.txt`).
