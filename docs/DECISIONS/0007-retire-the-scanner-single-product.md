# ADR 0007 — Retire the scanner; the combine platform is the only product

**Date:** 2026-08-07
**Status:** Accepted — supersedes ADR 0001

## Context

ADR 0001 chose to build the football+tennis combine platform as a **second** product
sharing one engine with the pre-existing multi-sport scanner (`scan.py`, `tools/
daily_report.py`, `daily.yml`, and the roughly thirty sports `tools/collect_live.py`
watched), on the grounds that minimising risk to a live system the operator already
depended on outweighed the cost of running two products side by side.

The operator's own instruction, once the combine platform was live and verified, was
explicit and went the other way:

> "Eski yapıyı ortadan kaldır. Sadece tenis ve futbol olacak ve yeni yapı ile
> ilerleyeceğiz." — Remove the old structure. Only tennis and football from here on;
> proceed exclusively with the new structure.

This is not a request that can be satisfied by extension. It reverses ADR 0001's premise:
the scanner is not being kept alongside the new platform any more, and the product's
sport scope is not "every sport a model can reach" but a fixed two.

## Decision

- **Retire the scanner as a product surface.** `scan.py`, `engine/score.py`,
  `engine/report.py`, `engine/parser.py`, `tools/daily_report.py`, `tools/
  make_picks_page.py`, `tools/make_stats_page.py`, `tools/make_method_page.py`,
  `tools/daily_results.py`, `tools/refresh_coupon.py`, `tools/make_coupon.py`,
  `engine/stake.py`, and the workflows `daily.yml` and `collect-results.yml` are deleted,
  not deprecated in place. `engine/parlay.py` is trimmed to the one function
  (`betwinner_url`) the combine platform actually calls; its scan-only parlay-summary
  functions, which read a field (`overround`) nothing in the surviving pipeline computes,
  go with the rest.
- **Fix the product's scope at football and tennis.** `engine/pick.py`'s
  `MODELLED_SPORTS` — already down to `{10}` (table tennis) after football moved onto the
  generic model earlier this session — goes to empty: table tennis leaves the *set* the
  same way football did, but because its sport leaves the *product* entirely, not because
  a second sport passed the generic model's calibration. `engine/model_tt.py`,
  `engine/setka.py`, and the table-tennis-only collectors (`tools/collect_tt.py`,
  `tools/harvest_tt_history.py`, `tools/build_tt_model.py`) are deleted, not kept dormant
  — unlike the still-present but now-unreachable football-Elo branch in
  `pick.resolve()`, which stays because re-admitting football's own hand-written model
  is a one-line change within the surviving scope, not a scope change itself.
  `tools/collect_live.py`'s watch list (`SPORTS`) narrows from ~30 finish conditions to
  two; `tools/collect_results.py`'s `ADAPTERS` narrows from six to three (football, TML,
  tennisexplorer). Historical result data for other sports already in
  `data/results/*.jsonl` is left in place — deleting collected data is a different,
  larger decision than deleting the code that collects more of it, and this ADR does not
  make that decision.
- **The combine platform's daily run (`combine.yml`) becomes the only scheduled product
  workflow.** It gains the results-store refresh and football/tennis model refit that
  `daily.yml --all` used to provide (now `--sport 1`/`--sport 4` explicitly, not `--all`,
  since the store may still hold other sports' historical rows), and a Telegram
  notification step (`tools/notify_combine.py`), reusing the existing
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` secrets and channel — no second bot, per the
  operator's instruction. `results.yml` narrows to settling combines, refreshing the
  bet-slip code (`tools/refresh_combine.py`, replacing `tools/refresh_coupon.py` on the
  new artifact shape), and rebuilding the 14 platform pages; its old singles-list steps
  (grading `predictions.jsonl`, rebuilding `results.html`/`stats.html`) are removed along
  with the code they called. `watch-live.yml`'s mechanics are unchanged — its scope
  narrows automatically because `collect_live.SPORTS` does — but its extensive "why every
  sport" comment block is rewritten to describe the fixed two-sport reality instead.
- **`CLAUDE.md` itself is rewritten**, not left describing a retired product as current.
  It is auto-loaded as override-priority operating instructions every session; a stale
  CLAUDE.md is actively worse than none, because it would confidently give the wrong
  answer instead of no answer. Sections describing the scanner's own product identity
  (composite score, top-N deliverable, opt-in parlay, the multi-sport "adding a sport"
  procedure) are rewritten for the combine platform. Sections describing infrastructure
  that did not change — coupon/slip mechanics, the live watcher's finish-condition logic,
  the source-qualification hard rules (9–11) — are kept, narrowed only where the sport
  list itself narrowed.

## Consequences

- **One product, one engine, one daily workflow.** Nothing in this repo produces a top-N
  singles list, a `--parlay` opt-in summary, or a picks/results/stats/method page set any
  more. `docs/ARCHITECTURE.md` and `README.md` describe one pipeline, not two.
- **A real, disclosed gap this ADR closes rather than leaves open:** deleting
  `tools/refresh_coupon.py` (it imported the deleted `make_picks_page`) would have
  silently dropped the mechanism that kept the daily coupon code from going stale as
  fixtures started — the exact "20 tekli bahis becomes a 13-leg kombine" failure
  `engine/coupon.py`'s own docstring already documents. `tools/refresh_combine.py`
  replaces it on `combine.json`'s shape, wired into `results.yml` hourly, and
  `tools/daily_combine.py`'s `serialize_leg()` now carries the betslip `game_id`
  specifically so that refresh can run.
- **A known, accepted reduction in scope, not a bug:** the live watcher, the results
  store, and the generic model's calibration gate all still work exactly as designed for
  any sport — narrowing `collect_live.SPORTS` and `collect_results.ADAPTERS` to
  football+tennis is a product decision, reversible by re-adding entries, not a
  capability that was lost. `MODELLED_SPORTS` being empty does not mean the hand-written-
  model mechanism was removed; it means nothing in the current scope needs one right now
  (hard rule 8: a model earns admission on calibration, not on having been written).
- **The old scanner's daily picks list, its `report.json`/`daily_report.json` output, and
  its within-book "cheapness" ranking no longer exist anywhere in this repo**, including
  as a manually-run tool. Recovering that product would mean restoring the deleted files
  from git history, not flipping a flag.
- Hard rule numbering (`CLAUDE.md`) is preserved where a rule's content survives, even
  though several rules' *text* changed to describe the combine platform instead of the
  scanner — renumbering would have broken every cross-reference to a hard rule by number
  across `docs/`, the test suite, and this ADR itself.
