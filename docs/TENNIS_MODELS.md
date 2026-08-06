# TENNIS_MODELS.md

## Status today: `RESEARCH_ONLY` / `BLOCKED_BY_EXTERNAL_ACCESS` for live picks

Tennis (Betwinner `sport_id = 4`) produces **zero picks in the live pipeline right now**,
before and after this session's changes. This is stated plainly because `CLAUDE.md`'s own
prose ("the generic gate now admits ALL FIVE sports... tennis 0.012") is **stale** relative
to the actual repo state as of 2026-08-06 — `data/models/4.json` carries
`"calibration": []`, and `engine/model_generic.usable()` refuses any model with no
calibration table outright. This document records the real, measured reason, what this
session fixed, what it deliberately did not, and the concrete next step — because "tennis
is refused" without a reason is indistinguishable from a model nobody has looked at.

## Two real bugs fixed this session (verified, tests pass, safe for any sport)

1. **`surface` was being read by nothing.** TML-Database mirrors Sackmann's ATP schema and
   has carried a `surface` column in every year checked; `tools/collect_results.py`'s
   `tennis()` adapter parsed the file but never extracted it. Fixed: the field is now
   captured and stored (`engine/results_store.py`'s optional-field allowlist extended).
   Backfilled onto the 29,661 already-stored TML rows via
   `python3 tools/collect_results.py --source tml --restate` (run this session — verified
   in `data/results/4.jsonl`: 17,652 Hard / 8,859 Clay / 3,126 Grass / 14 Carpet / 123
   unlabelled). **Not yet used to partition rating pools** — see "What surface-awareness
   still needs" below.
2. **`model_generic.lookup()` added home advantage unconditionally**, even though every
   stored tennis row is marked `neutral: True` and `fit_ratings()` correctly skips
   `HOME_ELO` when *fitting* a neutral sport's ratings. Every *lookup*, though, still added
   +60 Elo to whichever side happened to sort first (lower book id / name) — a train/predict
   mismatch, not a modelling choice. Fixed: `lookup()` now takes a `neutral` parameter
   (default `False`, so every existing caller — football, basketball, baseball, table
   tennis fallback — is byte-for-byte unaffected); `engine/pick.py` defines
   `NEUTRAL_SPORTS = {4}` and passes `neutral=True` for tennis specifically.

Both changes: full existing test suite (71 tests) passes unchanged before and after.

## The actual blocker: measured, not assumed

`tools/build_generic_model.py`'s calibration is a chronological 80/20 split **by row
count**, evaluated only on rows where both sides clear `MIN_APPEARANCES=20` in the training
slice — deliberately, so the check measures the model that would actually run, not one that
prices everyone. For tennis specifically:

```
total rows:  38,724
train:       30,979 (2015-01-04 → 2026-07-26) — 29,774 tml + 1,205 tennisexplorer
test:         7,745 (2026-07-26 → 2026-08-06) — 4,654 tennisexplorer + 3,091 betwinner-live
test rows where BOTH sides clear MIN_APPEARANCES from train:  0 / 7,745
```

The test window is **eleven days**, not a representative fifth of the archive's time span,
because row *density* is wildly non-uniform: TML contributes roughly 2,700 matches/year
across eleven years (sparse, tour-level only), while tennisexplorer + the live watcher
contribute thousands of matches in the final weeks alone (dense, and dominated by
Challenger/ITF/qualifying names that essentially never appear in TML's tour-level archive
at all — `Ciric Bagaric L.`, `Von Der Schulenburg J.`, etc.). An 80/20 split **by row
count** therefore allocates almost the entire test window to a population the training
window barely covers, independent of surface, independent of the neutral-venue fix, and
independent of how current TML's archive is. Confirmed directly: only 416 of 8,977 distinct
players/teams in the whole store clear the 20-appearance floor at all.

This is the calibration gate **doing its job** (hard rule 8: "a wrong row is
indistinguishable from a real one once it is inside a rating"), not a bug to route around.
Loosening `MIN_APPEARANCES` or the calibration threshold to force tennis through would be
exactly the kind of gate-bypass hard rule 8 forbids, and this session does not do it.

## What was deliberately NOT attempted

- **Changing the 80/20-by-row-count split to a date-proportional one**, which would very
  plausibly fix this (a time-based test window would include a healthier mix of the
  well-covered tour-level population instead of being swamped by a recent density spike).
  Not attempted because `tools/build_generic_model.py`'s `build()` is **shared by every
  sport** (football, basketball, baseball, table tennis all calibrate through the same
  function), and changing it without separately re-validating each of their calibration
  gaps is exactly the kind of unreviewed structural change the platform's new governance
  layer (`docs/MODEL_GOVERNANCE.md`) exists to gate. Filed instead as a **ProposedModelChange**
  (`data/proposed_changes.jsonl`, id `pmc-2026-08-06-tennis-split`) for explicit operator
  review — see that file and the "Önerilen Model Değişiklikleri" screen.
- **Adding tennis-data.co.uk as a second tour-level source.** Reachable in general, but this
  sandbox's egress could not complete a TLS handshake to it (`tennis-data.co.uk`, distinct
  from the TML/GitHub path which works fine) — recorded as `BLOCKED` in
  `docs/DATA_SOURCES.md`, worth a retest from a plain GitHub Actions runner. It would not,
  on its own, have fixed the calibration gap regardless: `research/tennis.json`'s own notes
  already flag it as **main-tour only**, the same population TML already covers — the
  gap is in the Challenger/ITF/qualifying tail, which no currently-catalogued free source
  reaches with enough density (`docs/DATA_SOURCES.md`'s tennisexplorer entry is the closest,
  and it is exactly what's already wired in and still thin).
- **Surface-partitioned rating pools** (`pool = "bo3|clay"` etc.). Would fragment an
  already-insufficient dataset further and make calibration strictly harder to pass, not
  easier, while the underlying population-coverage gap remains unsolved. The `surface`
  field is stored and ready for this the day the coverage question is actually resolved —
  see below.

## What surface-awareness still needs before it can partition anything

Even with `surface` now stored, using it to split rating pools needs the field at **both**
training time (have it — TML) **and** inference time (do not have it): Betwinner's own
card does not publish a surface indicator per tennis fixture, and tennisexplorer (the only
source dense enough to cover the recent/lower-tier population) does not carry it either.
A name/tournament-based surface guess for the live card was considered and rejected for
this session — a silently wrong surface guess is exactly the class of error hard rule 10
exists to prevent, and it would be very hard to detect from the outside (unlike an outright
refusal). This is recorded as backlog in `docs/ROADMAP.md`, not attempted half-done.

## What this means for the rest of the platform this session

The confidence scoring, data-quality scoring, referee board, and combine optimizer built
this session (`docs/CONFIDENCE_SCORING.md`, `docs/REFEREE_BOARD.md`,
`docs/COUPON_OPTIMIZATION.md`) are all **sport-agnostic** — they consume whatever
`engine/pick.py` produces and do not know or care whether a given day's picks include
tennis. They are verified against synthetic tennis-shaped fixtures (same style as the
existing test suite's synthetic football `probs` dicts) so that the day tennis does clear
`model_generic.usable()` — either from more tennisexplorer history accumulating naturally,
or from the proposed split-methodology change being reviewed and approved — it flows
through the whole platform with no further wiring. Nothing in this session's new code
special-cases "assume tennis works"; it special-cases "handle a sport producing zero
picks today," which is the honest current state.
