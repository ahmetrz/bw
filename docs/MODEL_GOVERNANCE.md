# MODEL_GOVERNANCE.md

## Two different things, governed differently — read `docs/DECISIONS/0004` first

The platform brief says: "İnsan onayı olmadan üretim modelini, eşikleri veya aktif
kuralları değiştirme." Taken completely literally that would forbid the daily automatic
model refit that has been running in production since before this session
(`tools/build_generic_model.py --all`, called from `daily.yml`). It does not forbid it,
because **routine recalibration is not the kind of change that sentence is about**:

| | Routine recalibration | Structural change |
|---|---|---|
| What changes | the DATA behind a fixed method | the METHOD itself — weights, thresholds, calibration technique, which model is authoritative |
| Example | today's Elo fit includes today's new results | switching the calibration split from row-count-proportional to date-proportional (the live tennis proposal) |
| Gate | `model_generic.usable()`'s own held-out calibration check, every single refit | `engine/governance.propose()` → human review → manual code change |
| Automatic? | yes, always has been | never — nothing in this repo calls a matching `apply()` |
| Reversible? | yes — `engine/governance.archive_model_version()` snapshots the previous model before every refit | yes — it's a normal code change, reviewed like any other |

## `engine/governance.py` — what it actually does

**`propose(id, category, title, description, evidence, current_value, proposed_value,
requires_backtest)`** writes one record to `data/proposed_changes.jsonl` with
`status="proposed"`. Idempotent on `id` — re-filing the same finding updates it in place
rather than duplicating the review queue, but only while it is still `proposed`; once a
human has reviewed it, re-proposing the same `id` is refused (`propose()` returns the
existing, already-reviewed record unchanged) — resurrecting a rejected proposal under the
same id would let an automated process silently overrule a human decision.

**`review(id, decision, reviewer, note)`** is the ONLY function that changes `status`, and
it requires an explicit `"approved"` or `"rejected"` — there is no default, no timeout-based
auto-approval, and calling this function is a human action (a script invoked by the
operator, not a scheduled job).

**Categories** (`governance.CATEGORIES`): `weight_change`, `threshold_change`,
`market_pause`, `league_pause`, `source_reliability_change`, `new_feature`,
`module_disable`, `calibration_method_change`.

## The first real proposal this session filed

`pmc-2026-08-06-tennis-split` — a genuine finding, not a demonstration example. Full
evidence and reasoning in `docs/TENNIS_MODELS.md`; short version: tennis's calibration test
window is 11 days by construction of a row-count-proportional split colliding with a recent
density spike from a new data source, and 0 of 7,745 test rows have both sides measurable
from training. The proposed fix (a date-proportional split) is filed, `status="proposed"`,
untouched by any automated process, visible on the "Önerilen Model Değişiklikleri" screen
and in the PDF-equivalent governance section — waiting for the operator, exactly as
designed.

## Model version history

`archive_model_version(sport_id)` copies whatever is currently at
`data/models/<sport_id>.json` to `data/models/history/<sport_id>/<date>_<games>g.json`
**before** `tools/build_generic_model.py` overwrites it — called from inside `build()`
itself, so this happens on every single refit, not just ones an operator remembers to
trigger. Keeps the most recent 30 snapshots per sport (roughly a month of daily refits).
`list_model_versions(sport_id)` reads them back; rendered on `model_versions.html`. Rolling
back means copying an archived file over the current one by hand — deliberately manual,
matching "yeni sürüm rollback edilebilir olsun" without adding an automated rollback path
that could fire without a human deciding to.
