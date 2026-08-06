# OPERATIONS.md

Day-to-day operation of the combine platform, for the operator. Setup is
`docs/LOCAL_SETUP.md`; this is what running it actually looks like once it's live.

## The daily cycle

1. **~09:43 Istanbul** (`daily.yml`, inherited cadence — see `docs/GITHUB_ACTIONS.md`'s open
   cadence item): the card is fetched once, the existing daily-picks list is built, then
   the combine platform runs against the SAME card — confidence scoring, referee board,
   combine optimizer, PDF, all 14 new pages. Either a combine exists or `combine.json` says
   plainly why not.
2. **Every hour, :30** (`results.yml`): finished legs get graded
   (`tools/grade_predictions.py` for the daily-picks list, `tools/grade_combine.py` for the
   combine) and every page rebuilds so the site reflects the day's actual state within the
   hour, not the next morning.
3. **~55 min of every hour** (`watch-live.yml`, unmodified by this session): the live
   watcher keeps accumulating results across every sport the book carries — this is what
   eventually gives the tennis calibration proposal (`data/proposed_changes.jsonl`) enough
   fresh data to reconsider.

## What to actually look at, and in what order

1. **`combine.html`** first — the day's answer. If it says no combine, the reason is on
   the same page (`why`), not buried in a log.
2. **`referee.html`** if a selection looks off — every judge's verdict is there, not just
   the final include/exclude call.
3. **`calibration.html`** / **`lab.html`** weekly, not daily — a single day's hit rate is
   noise (`docs/PERFORMANCE_METRICS.md`); these need `MIN_MEANINGFUL=20` graded samples
   before they say anything trustworthy at all, and will show an honest empty state until
   then.
4. **`proposed_changes.html`** whenever a governance proposal is filed — review it there,
   decide, and make the corresponding code change yourself
   (`engine/governance.review(id, "approved"|"rejected", your_name, note)`, then the actual
   structural change as a normal commit). Nothing applies a proposal automatically.
5. **`source_health.html`** if something looks stale or wrong — it says which upstream
   source is degraded or unavailable and since when.

## Reviewing a proposed model change

```python
from engine import governance
governance.list_proposals(status="proposed")               # see what's waiting
governance.review("pmc-2026-08-06-tennis-split", "approved", "ahmet",
                  note="agreed, will implement the date-proportional split")
```

Approving a proposal records the decision. It does not change any code — the operator (or
a future session) still has to make the actual change described in `proposed_value`, the
same as any other code change: edit, test, commit.

## Retention

Per the brief (section 18): a year of prediction/combine history, then controlled
retention. Not automated this session — `data/predictions.jsonl` and
`data/combine_log.jsonl` grow unbounded today. A yearly archive/compression pass is backlog
(`docs/ROADMAP.md`), not yet built; both files are append-only text and can be trimmed by
date manually (`date >= cutoff`) without touching the model layer, since nothing in
`engine/` reads more than the current model files.

## Rolling back a model

```python
from engine import governance
governance.list_model_versions(4)                          # tennis, e.g.
# copy the desired archived file over the live one:
#   cp data/models/history/4/2026-08-01_38200g.json data/models/4.json
```

Deliberately a manual `cp`, not a function call — a rollback is a decision, and the brief's
governance requirement (section 17) is about exactly this: a human acts, nothing acts for
them.

## When a combine was minted but the operator wants to place fewer legs

`engine/coupon.py`'s code loads as an ACCUMULATOR (`Vid=1`) — Betwinner does not support
loading a subset of a shared slip. Removing a leg by hand in the book's own "load bet slip"
screen after loading the code is the only way (same limitation the pre-existing scanner
product already documents in `CLAUDE.md`'s "What the book will not combine" section — this
session did not change that constraint, only which legs the code is built from).
