# ADR 0003 — Two confidence thresholds, not one reconciled number

**Date:** 2026-08-06
**Status:** Accepted

## Context

The existing scan/daily-picks product gates on `config.MIN_MODEL_SURVIVAL = 0.75`
(hard rule 4, tuned and live). The platform brief asks for a combine that only includes
selections scoring **80/100 or above** on `engine/rating.py`'s 0-100 score, which — per
hard rule 6 — equals the model's stated win probability once evidence is full. These are
two different numbers gating two different products.

Reconciling them into one (e.g. raising `MIN_MODEL_SURVIVAL` to 0.80 platform-wide) was
considered and rejected: it would silently tighten the existing, already-tuned, already-
live daily picks list and scan path for every sport it covers, not just football and
tennis, and hard rule 3's existing product ("top-N SINGLES table... do not emit a parlay
by default") has no stated need for an 80-point floor — its own floor was chosen and
tuned for a different purpose (a wide informative list, not a single high-bar combine).

## Decision

- `config.MIN_MODEL_SURVIVAL` (0.75) keeps gating the scan and daily-picks list, unchanged.
- `config.MIN_COMBINE_CONFIDENCE` (80.0) is a new, separate, additional filter applied
  only inside `engine/combine.py`, only to the football/tennis combine candidate pool,
  on top of (not instead of) the existing 0.75 floor a pick already had to clear to exist
  at all.
- A selection can appear on `picks.html` (scored 75-79) and simultaneously be ineligible
  for that day's combine. This is not a bug — it is two products with two different bars,
  by design, and the combine page says so explicitly rather than implying the two lists
  should match.

## Consequences

- No change whatsoever to the live scan/daily-picks pipeline's behaviour or its already-
  measured calibration.
- The combine product can end up empty far more often than the daily-picks list does
  (which is correct: section 15/29 of the brief explicitly wants "kalite kriterlerini
  karşılayan uygun kombine bulunamadı" as a normal, frequent, honest outcome — not a
  failure state to paper over by borrowing the looser threshold).
