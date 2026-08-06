# TENNIS_MODELS.md

## Status: `IMPLEMENTED_AND_VERIFIED` — tennis now produces picks

Tennis (Betwinner `sport_id = 4`) was refused by `engine/model_generic.usable()` for most
of this session (`data/models/4.json` carried `"calibration": []`) — `CLAUDE.md`'s own
prose ("the generic gate now admits ALL FIVE sports... tennis 0.012") was **stale** against
the actual repo state as of 2026-08-06. This document originally recorded that as a
measured, unresolved gap and filed a specific fix as a governance proposal rather than
forcing it through. **The operator reviewed and approved that proposal the same session**;
it is now implemented, measured, and tennis clears calibration at **0.023** (`data/models/
4.json`, 38,749 results). The rest of this document is kept in full — the diagnostic
reasoning is exactly why the fix works and exactly what it cost — with the resolution
recorded first.

## Resolution: `pmc-2026-08-06-tennis-split`, approved and implemented

`tools/build_generic_model.py`'s calibration split changed from row-count-proportional to
**date-proportional** (`_holdout_cut()`, new function) — see "What was deliberately NOT
attempted" below for why this needed approval before touching it, and `docs/MODEL_GOVERNANCE.md`
for the governance record. Rebuilding all sports with the new split, measured directly:

| Sport | Before (row-count split) | After (date-proportional split) |
|---|---|---|
| Football (1) | usable, gap 0.012 | usable, gap **0.010** (improved) |
| Basketball (3) | usable, gap 0.028 | **refused, gap 0.030** (regressed — see below) |
| Tennis (4) | **refused — empty calibration table** | **usable, gap 0.023** (fixed) |
| Baseball (5) | usable, gap 0.014 | usable, gap 0.014 (unchanged) |
| Table tennis (10) | usable, gap 0.015 | usable, gap **0.006** (improved) |
| Badminton (16) | usable, gap 0.024 | usable, gap **0.013** (improved) |

**Disclosed trade-off, not hidden:** basketball's gap moved from 0.028 to 0.030, crossing
the 0.03 admission bar it had been just inside of, and basketball is now refused. This is a
small, boundary-adjacent shift (0.002), and the calibration gate handled it exactly as
designed — a sport that no longer clears its own held-out check is excluded, not kept in on
a technicality (hard rule 8). It may resolve on its own as more basketball results
accumulate under the new split; it was not forced past the bar to avoid the regression,
because that would be precisely the gate-bypass hard rule 8 forbids. Tracked as a live
consequence in `docs/ROADMAP.md`, not swept into the "improved" column above.

A second real consequence, caught by the existing regression suite rather than assumed
away: `tests/test_regression.py::test_a_model_is_admitted_only_by_held_out_calibration`
used to assert `train_rows > test_rows` as its proxy for "this is a genuine, non-degenerate
holdout." That stopped holding for table tennis specifically — its live-watcher-fed recent
density is so much higher than its archive's that the last-20%-of-TIME test window now
contains *more* rows than the 80%-of-time train window, while remaining a perfectly valid,
non-overlapping split. The test was corrected to check the actual property that matters
(train's last date precedes test's first date) rather than the row-count proxy that used to
imply it — see `tools/build_generic_model.py`'s `calibration_holdout.train_to`/`from`
fields, added in the same change.

`engine/pick.py` needed no further wiring: tennis flows through the same
`generic.get(sport)` path every non-hand-written sport already uses, gated purely by
`model_generic.usable()` — the moment the calibration table is non-empty and clears 0.03,
the daily-picks pipeline and the combine platform both pick it up automatically.

## Two real bugs fixed earlier the same session (verified, tests pass, safe for any sport)

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

## What was deliberately NOT attempted without review first

- **Changing the 80/20-by-row-count split to a date-proportional one directly**, without
  going through review, even though the fix was already identified and plausible at
  diagnosis time. `tools/build_generic_model.py`'s `build()` is **shared by every sport**
  (football, basketball, baseball, table tennis all calibrate through the same function),
  so a change here needed a human to weigh "fixes tennis" against "may re-validate (or
  regress) four other sports' calibration gaps that already pass" BEFORE it shipped — which
  is exactly what happened: filed as a **ProposedModelChange**
  (`data/proposed_changes.jsonl`, id `pmc-2026-08-06-tennis-split`, `status: "approved"`),
  reviewed by the operator, and only then implemented and measured (see "Resolution"
  above, including the basketball trade-off that review process was specifically there to
  surface rather than ship silently).
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

## What this means for the rest of the platform

The confidence scoring, data-quality scoring, referee board, and combine optimizer built
this session (`docs/CONFIDENCE_SCORING.md`, `docs/REFEREE_BOARD.md`,
`docs/COUPON_OPTIMIZATION.md`) are all **sport-agnostic** — they consume whatever
`engine/pick.py` produces and never special-cased "assume tennis works" or "assume tennis
is dark." They were built and verified against synthetic tennis-shaped fixtures precisely
so that the day tennis cleared `model_generic.usable()` (now: this session, via the
approved split) it would flow through the whole platform with zero further wiring — which
is exactly what happened. The same genericity means a sport dropping OUT of `usable()`
(basketball, today, from the same change) is handled by the identical code path: no
special-casing needed either way, because "a sport currently produces zero picks" was
always a normal, expected state for this pipeline to be in, not an edge case bolted on
afterward.
