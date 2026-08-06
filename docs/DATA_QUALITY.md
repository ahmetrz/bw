# DATA_QUALITY.md

`engine/dataquality.py` — a 0-100 score per candidate selection, decomposed into named,
reason-coded components, reusing the SAME underlying signals `engine/rating.py` already
computes (name-match confidence, sample size) rather than a second, differently-weighted
copy of them. The discount `rating.py` applies to the confidence score already IS a data-
quality judgement; this module is the transparency layer that breaks it out by reason,
per the platform brief's section 8.

## The eight reason codes, exactly as named in the brief

| Code | Component | Fires when |
|---|---|---|
| `CRITICAL_ODDS_MISSING` | `_odds_completeness` | odds absent or ≤1.0 — a safety-net check; `engine/pick.py`'s own contract already requires odds on every emitted selection, so this should never actually trigger in practice |
| `STALE_EVENT_DATA` | `_staleness` | `staleness_seconds` over ~5 minutes; reported as `INFO`-severity "unmeasurable" when the source carries no per-selection timestamp at all (Betwinner's own feed — `engine/bwfeed.py`'s `changed_at` is always `None`) |
| `PLAYER_IDENTITY_UNCERTAIN` | `_name_identity` | `name_match` below 1.0 — a fuzzy rather than exact/book-id match was used to resolve the fixture |
| `INSUFFICIENT_SAMPLE` | `_sample_size` | fewer than 1,500 matches behind the rating (full marks) / fewer than 400 (major discount) |
| `MARKET_MAPPING_UNVERIFIED` | `_market_mapping` | `settlement.needs_confirmation` is true for this market |
| `LINEUP_DATA_UNAVAILABLE` | always attached, `INFO` | this platform integrates no lineup/injury source at all — disclosed on every selection, not a per-selection judgement |
| `SOURCE_CONFLICT` | always attached, `INFO` | one odds source (Betwinner) only; cross-source consistency cannot be checked — disclosed on every selection |
| `RESULT_VERIFICATION_UNAVAILABLE` | `_result_verifiability` | `results_store` holds fewer than 100 results for this sport — the outcome may not be independently checkable later |

## Severity, and what each level actually does

- **`critical`** — `dataquality.assess()["blocks_combine"] = True`, `score` forced to 0.
  `engine/combine.eligible()` excludes the pick outright, independent of its confidence
  score (`tests/test_combine_platform.py::test_critical_data_quality_directly_excludes_a_leg`).
- **`major`** — a large weighted discount to the 0-100 score; `engine/referee.data_quality_judge`
  vetoes below 40, flags below 65.
- **`minor`** — a small discount; disclosed, does not veto on its own.
- **`info`** — disclosed, contributes NOTHING to the score. This is the level
  `LINEUP_DATA_UNAVAILABLE` and `SOURCE_CONFLICT` always sit at: an honest "we don't have
  this" is not the same claim as "we checked and it's a problem," and scoring it as if it
  were would punish every single selection identically for a structural platform limit
  rather than a fact about that specific pick.

## Weighting (`dataquality.WEIGHTS`)

```
identity: 0.30   sample: 0.30   odds: 0.15   staleness: 0.10   market: 0.15
```

`result_verifiability` is disclosed but **not** weighted into the score — it describes
whether this platform can grade the pick LATER, not the quality of the pick NOW. Folding
it into the same score would conflate two different questions.

## What this is not

Not a second confidence score. `engine/combine.py` gates on `confidence_score` (from
`engine/rating.py`, hard rule 6) and separately on `data_quality["blocks_combine"]` — two
independent checks, reported independently, never blended into one number that would hide
which one a low result is actually about.
