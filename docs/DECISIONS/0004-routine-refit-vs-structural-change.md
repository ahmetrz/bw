# ADR 0004 — Routine model refit is automatic; structural change is not

**Date:** 2026-08-06
**Status:** Accepted. Note (2026-08-07, `docs/DECISIONS/0007`): the refresh step this ADR
describes now lives in `combine.yml` (`daily.yml` was deleted with the scanner it served),
and runs `--sport 1`/`--sport 4` explicitly rather than `--all` — the results store may
still hold other, now-out-of-scope sports' historical data, and there is no reason to
spend a daily refit on a model nothing reads. The DECISION itself (routine recalibration
automatic and gated only by `model_generic.usable()`; structural change through
`engine/governance.propose()`, never auto-applied) is unchanged.

## Context

The platform brief (section 17) says: "İnsan onayı olmadan üretim modelini, eşikleri veya
aktif kuralları değiştirme" (do not change the production model, thresholds, or active
rules without human approval). Taken literally, that would forbid
`tools/build_generic_model.py --all`, which already runs unattended, once a day, inside
`daily.yml`, and rewrites every sport's model file from freshly accumulated results
(`CLAUDE.md`: "Sonuc deposunu ve modelleri her gun tazele"). That mechanism is not new —
it predates this session, it is how every sport currently in production got there, and
hard rule 8 (a model is admitted on its OWN held-out calibration, checked every time it
refits) is the safety mechanism the brief's own worry is aimed at.

## Decision

Two different things both get called "the model changing," and they are governed
differently:

- **Routine recalibration** — refitting the SAME methodology (chained Elo, margin-of-
  victory, counted bands, 80/20 held-out calibration) on more results than yesterday.
  Stays automatic, gated only by `model_generic.usable()`'s existing calibration check.
  Nothing about the METHOD changes; only the DATA behind it grows. `engine/governance.py`
  now archives an immutable copy of each sport's model before every refit
  (`archive_model_version()`), so this mechanism also gets a rollback path — but rollback
  capability is not the same as approval-gating, and this ADR does not add the latter.
- **Structural change** — a different weight, a different threshold, a different
  calibration METHOD, retiring a market/league, changing which model is authoritative for
  a sport. Goes through `engine/governance.propose()`, is never auto-applied by any code
  in this repo, and is rendered on the "Önerilen Model Değişiklikleri" screen for the
  operator to act on manually.

## Consequences

- `daily.yml`'s existing "Refresh the results store and rebuild every model" step needed
  no change to its trigger condition or schedule — it already only ever produces a result
  that is either admitted by calibration or refused by it, same as before this session.
- The first real structural proposal this session produced —
  `pmc-2026-08-06-tennis-split` (see `docs/TENNIS_MODELS.md`) — sits in
  `data/proposed_changes.jsonl` with status `proposed` and is not applied anywhere.
