# CONFIDENCE_SCORING.md

## The one rule everything here obeys

**The confidence score is the model's calibrated win probability, discounted by evidence
— nothing else ever enters it.** This is hard rule 6 in `CLAUDE.md`, it predates this
session, and every addition here extends it rather than works around it. The literal
formula, from `engine/rating.py` (unchanged this session):

```
puan = 100 × ( eşik + (olasılık − eşik) × kanıt )
```

`eşik` (floor) is `config.MIN_MODEL_SURVIVAL` (0.75) for the daily-picks path;
`engine/confidence.py` calls the exact same function with the exact same floor for the
combine platform — there is no second scoring formula. Verified by
`tests/test_combine_platform.py::TestConfidence::test_confidence_score_equals_ratings_score_exactly`
and `test_score_never_reads_the_price_through_confidence_either`, which assert the number
is byte-identical to `rating.score()`'s own output and provably blind to the odds.

## What `engine/confidence.py` adds on top

The platform brief (section 12) asks for a full record per candidate, not just a number.
`confidence.build(pick)` returns:

| Field | Source | Notes |
|---|---|---|
| `estimated_probability` | `pick["model_survival"]` | the model's own number, unmodified |
| `model_uncertainty` | `1 - evidence_pct/100` | inverse of rating.py's evidence discount |
| `data_quality` | `engine/dataquality.assess()` | full reference: `docs/DATA_QUALITY.md` |
| `market_reliability` | `settlement.needs_confirmation` | `"confirmed"` or `None`, never guessed |
| `model_consensus` / `contradiction_score` | a second model's direction, IF one also reached the fixture | `None` when no second opinion exists — not fabricated as agreement |
| `bookmaker_odds`, `implied_probability` | the pick's own odds | 1/odds, reported not used for selection |
| `corrected_probability` | — | always `None` — no non-proportional de-vig method is implemented (`DATA_CONTRACT.md`); a number here would look precise and mean nothing beyond what `margin_score` already reports |
| `expected_value` | `model_prob × odds - 1` | **diagnostic only** — see below |
| `confidence_score`, `confidence_band` | `rating.score()`, verbatim | the number described above |
| `factors.up` / `factors.down` | translated from the same evidence numbers | not a second judgement — plain-language labels on numbers already computed |
| `risks` | settlement uncertainty, low data quality, thin ladder | |
| `data_sources`, `model_version`, `analysis_timestamp` | | reproducibility fields, section 23 |

## Why EV is reported but never used to select

`engine/edge.py` (pre-existing) already states the reasoning for the daily-picks path: a
computed positive edge against a free public model is far more often model error than a
real mispricing, because the model is not sharper than a bookmaker's own pricing. Section
12 of the brief asks for EV to be *reported* — this session does exactly that and no more.
`engine/referee.py`'s `odds_ev_judge` goes one step further and treats an implausibly large
computed EV (+35% or more) as a reason to **flag the selection as suspicious**, not as a
reason to prefer it — the inversion is deliberate and is the same judgement `edge.py`
already made, applied per-leg.

## Reproducibility

Every `ConfidencePrediction` carries `model_version` (a fingerprint of source + sample
size behind the rating, e.g. `elo-141457g`) and `analysis_timestamp`. The combine as a
whole additionally carries `config_fingerprint` (`tools/daily_combine.config_fingerprint()`
— a short hash of the thresholds in force) in `combine.json`/`data/combine_log.jsonl`, so a
past day's combine can be read back with exactly the settings that produced it, per section
23's reproducibility requirement.
