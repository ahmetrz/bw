# SELF_LEARNING.md

## What is logged, and why it can never be quietly rewritten

`data/combine_log.jsonl` — one row per day, appended once by `tools/daily_combine.py` at
generation time, in the exact shape `combine.json` has (legs, confidence, referee verdicts,
data quality, `config_fingerprint`, `min_combine_confidence`). The **selection fields are
written once and never touched again** — same discipline `tools/daily_report.log_predictions`
already applies to `data/predictions.jsonl`, for the same reason: a record edited after the
fact could quietly become "what we would have built," which is exactly the self-deception a
learning loop exists to prevent.

The one field that DOES get filled in later is `settlement` — starts `None`, filled in by
`tools/grade_combine.py` once every leg in that day's combine has an independently-sourced
result. This mirrors how `data/predictions.jsonl` rows start with `result: None` and get it
filled in by `tools/grade_predictions.py`; it is not an exception to "never rewritten," it
is the same one exception the pre-existing log already has.

## What gets measured (`engine/track_record.py`)

- **`calibration_by_sport()`** — claimed vs. realised win rate per sport, gated at
  `MIN_MEANINGFUL = 20` graded selections (the same small-sample discipline
  `tools/make_stats_page.py` already uses for the daily-picks product). This is the table
  that can say a model is **wrong**, not merely unlucky — `docs/CONFIDENCE_SCORING.md` and
  `CLAUDE.md`'s hard rule 8 both depend on exactly this check existing.
- **`brier_score()`** — mean squared error between stated probability and the 0/1 outcome,
  overall and per sport. Lower is better; a constant 50% guess scores 0.25.
- **`log_loss()`** — mean negative log-likelihood of the stated probability. A constant 50%
  guess scores ln(2) ≈ 0.693.
- **`market_history()`** — per market type, what fraction of old-enough (>48h past kickoff)
  predictions still have no result at all — this is a **data-source** health signal
  (is this market type gradeable in practice), not a model-quality signal, and
  `engine/referee.market_reliability_judge` reads it as exactly that.

All four read `data/predictions.jsonl` only — the daily-picks log, not
`data/combine_log.jsonl` — because it has far more graded history (one row per selection,
not one row per day) and the combine platform's own legs are a subset of the same
underlying model calls. A combine-specific calibration view (was the WHOLE combine right,
not just its legs individually) is `combine_history.html`/`combine_results.html`, sourced
from `data/combine_log.jsonl` directly.

## Precision/recall and ROI

Precision/recall were considered and are not reported as a headline metric: this product
does not classify a fixed universe of items into positive/negative in a way that maps
cleanly onto precision/recall (every "positive" prediction that survives the gates IS the
thing being measured; there is no labelled negative class to score recall against). Hit
rate, Brier score and log loss cover the same ground more directly for a probability-
calibration problem. ROI is computed **only** as the analytical figure `engine/stake.py`
and `engine/combine.COMBINE_STAKE_UNITS` already define — a flat notional unit, never a
real amount, never tied to any account (brief's explicit "ROI yalnızca teorik ve analitik
bir metrik" instruction).

## What "self-learning" does NOT mean here

It does not mean a model that updates its own weights from its own recent record without
review. `engine/model_generic.py`'s daily refit (`tools/build_generic_model.py --all`,
already running in `daily.yml` before this session) is **routine recalibration** — the same
fixed methodology re-fit on more data, gated by its own held-out calibration check every
time. It is not gated behind human approval, and `docs/DECISIONS/0004` explains exactly why
that is a *different* thing from a **structural** change (a new weight, a new threshold, a
new calibration method) — see `docs/MODEL_GOVERNANCE.md`.
