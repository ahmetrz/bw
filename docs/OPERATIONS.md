# OPERATIONS.md

Day-to-day operation of the combine platform, for the operator. Setup is
`docs/LOCAL_SETUP.md`; this is what running it actually looks like once it's live.

## The daily cycle

1. **07:43 Istanbul** (`combine.yml`'s primary run, with 08:43/09:43 backstops that skip
   themselves if today's combine already exists — `docs/DECISIONS/0006`): its own fetch
   pulls the next 24 hours of Betwinner's card, then the whole pipeline runs against it —
   direction/ladder/gates, confidence scoring, referee board, combine optimizer, PDF, a
   Telegram notification to the existing bot/channel, and all 14 platform pages. Either a
   combine exists or `combine.json` says plainly why not. The same run also refreshes the
   football/tennis results store and refits both sports' generic models
   (`tools/collect_results.py --all`, `tools/build_generic_model.py --sport 1`/`--sport 4`)
   so the NEXT day's run has fresher data — deliberately after the combine is built, not
   before, so a same-day partial refresh never leaks into the model the same day's combine
   used.
2. **Every hour, :30** (`results.yml`): finished legs get graded (`tools/grade_combine.py`),
   the bet-slip code is refreshed from legs that have not started yet
   (`tools/refresh_combine.py`), and every platform page rebuilds so the site reflects the
   day's actual state within the hour, not the next morning.
3. **~55 min of every hour** (`watch-live.yml`): the live watcher keeps accumulating
   football and tennis results — `tools/collect_live.py`'s watch list narrowed to just
   these two sports with the rest of the platform (`docs/DECISIONS/0007`; it used to watch
   roughly thirty). This is the mechanism that fed the tennis calibration fix
   (`data/proposed_changes.jsonl`'s `pmc-2026-08-06-tennis-split`, now approved and
   implemented — `docs/TENNIS_MODELS.md`) and keeps feeding both sports' daily refits.

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

(`pmc-2026-08-06-tennis-split` above is a real, already-resolved example, kept because it
shows the actual call shape — it was reviewed, approved, and implemented the same session
it was filed; see `docs/TENNIS_MODELS.md`. `list_proposals(status="proposed")` is what
surfaces whatever is genuinely still waiting today.)

Approving a proposal records the decision. It does not change any code — the operator (or
a future session) still has to make the actual change described in `proposed_value`, the
same as any other code change: edit, test, commit.

## Retention

Per the brief (section 18): a year of prediction/combine history, then controlled
retention. Not automated — `data/combine_log.jsonl` grows unbounded today, one row per day
(`data/predictions.jsonl` is the retired scanner's own historical log, `docs/DECISIONS/0007`
— it no longer grows, since nothing writes new rows to it, but it is left in place rather
than deleted). A yearly archive/compression pass is backlog (`docs/ROADMAP.md`), not yet
built; the log is append-only text and can be trimmed by date manually (`date >= cutoff`)
without touching the model layer, since nothing in `engine/` reads more than the current
model files.

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
screen after loading the code is the only way — the book's own limitation, documented in
`CLAUDE.md`'s "What the book will not combine" section, unrelated to which product built
the slip and unchanged by the scanner's retirement (`docs/DECISIONS/0007`).
