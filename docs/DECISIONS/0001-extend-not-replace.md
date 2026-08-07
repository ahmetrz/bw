# ADR 0001 — Extend the existing scanner; do not replace it

**Date:** 2026-08-06
**Status:** Superseded by ADR 0007 (2026-08-07) — the operator's later, explicit
instruction was to retire the scanner entirely and run the combine platform as the sole
product. Kept below unedited as the record of what was decided and why, at the time it
was decided; it was the right call given what was known then, and reversed once the
operator's own direction changed, not because it was wrong on its own terms.

## Context

The task brief asks for a from-scratch-sounding "professional football & tennis betting
analysis platform" — confidence scoring, a referee board, a daily combine, self-learning,
PDF reports, an 18-screen panel. `CLAUDE.md`, however, describes (accurately, verified by
reading the actual code and tests) an already mature, already-live system: `main` and the
working branch are the **same commit**, and the last twenty-odd commits before this session
are automated `daily:`/`results:` runs from `.github/workflows/daily.yml`, `results.yml`
and `watch-live.yml`, dated today. This is a production system with a real operator reading
its Telegram output, not a green-field repo.

That system already implements, in some form, a large fraction of what the brief asks for:
a calibrated per-sport model gated on held-out accuracy (hard rule 8), an explainable 0-100
confidence score that is provably blind to the book's own price (hard rule 6, with a test:
`test_score_never_reads_the_price`), a results feedback loop (live watcher + two result
adapters + grading + a cumulative stats/calibration page), safe Telegram delivery, and a
slip-code builder that verifies itself before handing a code to the operator. It does NOT
yet have: a tennis-specific (surface-aware) model, a referee board, a genuine multi-objective
combine optimizer that can output nothing, PDF reports, most of the 18 web screens, or a
human-approval-gated model-change governance layer.

## Decision

Build the new platform as an **extension** of the existing engine, not a parallel rewrite:
- Reuse `engine/model_generic.py`, `engine/rating.py`, `engine/pick.py`, `engine/ladder.py`,
  `engine/results_store.py`, `engine/coupon.py`, `engine/grade.py`, `engine/settlement.py`
  as-is wherever their contracts already satisfy the brief.
- Add new modules alongside them (tennis surface-Elo, referee board, combine optimizer,
  PDF, new web screens) that call into the existing engine rather than duplicating its
  logic.
- Never modify `daily.yml`, `results.yml`, or `watch-live.yml` file lists/commit behaviour
  without a concrete reason, and when a reason exists, keep the existing MINE-file/rebase-
  retry discipline those workflows already use for concurrent-write safety.
- Preserve every existing hard rule (`CLAUDE.md` "Hard rules" section) as a hard constraint
  on all new code, not just old code — in particular hard rule 6 (score never reads price)
  and hard rule 8 (a model earns production status on calibration, not reach).

## Consequences

- Slower than a rewrite would feel, because every new module has to be read into and
  reconciled with existing conventions before being written.
- Much lower risk to the live pipeline the operator already depends on.
- The brief's "80/100 minimum confidence for the combine" and the existing product's
  `MIN_MODEL_SURVIVAL=0.75` floor are DIFFERENT thresholds for DIFFERENT products (the
  existing top-N scan/daily-picks list vs. the new single daily combine) and are not
  reconciled into one number — see ADR 0003.
- New governance (human-approved model changes, ADR 0004) applies to STRUCTURAL changes
  going forward; it does not retroactively gate the existing daily generic-model retrain,
  which is a different, already-proven mechanism (see ADR 0004).
