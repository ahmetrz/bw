# MANUAL_DATA_IMPORT.md — the fallback path when a source is down

This is not a new feature. It documents a mechanism that already exists and already
satisfies the brief's requirement that manual import stay available
("manuel içe aktarma çalışır durumda kalsın") if Betwinner's API or another data source
is unreachable. Nothing below required new code this session — it required reading
`scan.py`, `tools/daily_report.py`, `engine/bwfeed.py` and `engine/results_store.py`
closely enough to say plainly what they already do.

Two independent things can need manual replacement: the **odds card** (what to price)
and **results** (what a model learns from). They have two different mechanisms, because
they were already built for two different reasons — `--input` exists so a run can be
pointed at any saved pull, and the results store exists so any adapter can feed the same
table. Neither was built for this doc; both already cover it.

## The odds card: `--input` already is manual import

`scan.py`, `tools/daily_report.py`, and (through `tools/daily_report.load()`)
`tools/daily_combine.py` all take:

```
--input <path to a JSON or .json.gz file>
```

There is no separate "import" flag or format. Pointing `--input` at a file you saved by
hand — copied from a browser session, retrieved another way, or reconstructed from a
cache — **is** the manual-import path. If Betwinner's live feed is unreachable from
wherever the scheduled workflow runs, dropping a file at, say, `data/manual_pull.json`
and running

```
python3 tools/daily_report.py --input data/manual_pull.json --no-coupon
```

is the whole procedure. `daily.yml` already has a version of this for a different reason
(`use_committed_card: true` copies `data/card_today.json.gz` over the expected input path
instead of fetching — see `docs/GITHUB_ACTIONS.md`), which is the same mechanism used for
a different trigger.

### The shape it must match

The file must be a JSON array of Betwinner's own `GetGameZip` `Value` objects — the exact
shape `engine/bwfeed.py`'s module docstring reverse-engineers field by field (`CI` the
game id, `O1`/`O2` team names, `S` kick-off in unix seconds, `GE[]` market groups, and so
on). `engine/bwfeed.is_bwfeed()` is the literal gate every one of these tools runs the
file through:

```python
isinstance(data, list) and bool(data) and isinstance(data[0], dict) \
    and "GE" in data[0] and "CI" in data[0]
```

`fixtures/sample.json` (49 entries) is a real, checked-in example of this exact shape —
open it if you need a concrete reference for field names rather than relying on the
docstring alone. This is **not** a simplified or human-authored format: a hand-built file
has to carry the same abbreviated keys the live feed uses, because nothing downstream
transforms it further before `engine/bwfeed.normalize()` runs.

`.json.gz` is accepted everywhere `.json` is — both `scan.py` and
`tools/daily_report.load()` pick the opener from the file extension, which is why the
scheduled workflow stores its 48-hour pulls gzipped.

### `scan.py` is more permissive than the daily tools — know which one you're using

`scan.py` accepts a second shape too: an OddsPapi `odds-by-tournaments` response
(`engine/parser.py`), and picks whichever of the two normalizers matches
(`bwfeed.is_bwfeed(data)` first, `parser` otherwise). `tools/daily_report.py` and
`tools/daily_combine.py` do not — they call `bwfeed.is_bwfeed()` directly and refuse to
proceed if it's false:

```
Input is not a Betwinner feed pull — refusing to proceed.
```

This is deliberate, not an oversight: hard rule 5 ("never fabricate odds or limits... if
the loaded data's book ≠ the requested book, STOP") is stricter for the products that
actually notify the operator and log a permanent prediction than it is for the scan path,
which already prints a mismatch warning (`report.warn_book`) rather than refusing
outright. A manually assembled file for the daily pipeline has to be genuinely
Betwinner-shaped; there's no book-mismatch mode to fall back on there.

## Results: writing directly to `data/results/<sport_id>.jsonl`

Every sport's results — used to fit `engine/model_generic.py`, nothing else — live in
one file per sport, one JSON object per line, in the shape `engine/results_store.py`'s
`clean()` enforces. This is the same store every adapter in `tools/collect_results.py`
writes to (`football` → sport 1, `euroleague` → 3, `tml`/`tennisexplorer` → 4, `mlb` → 5,
`setka` → 10 — see `ADAPTERS` in that file, or run `python3 tools/collect_results.py
--list`), and the live watcher (`tools/collect_live.py`) writes to it too. A manually
supplied result is not a special case to the model — it's another row in the same table.

### Required fields (`results_store.REQUIRED`)

A row missing any of these, or with a non-numeric score, is not stored — `clean()`
returns `None` for it rather than repairing it:

| Field | Type | Notes |
|---|---|---|
| `date` | string | Truncated to `YYYY-MM-DD` regardless of what's passed in |
| `home` | string | Must be non-empty after stripping |
| `away` | string | Must be non-empty after stripping |
| `home_score` | int (or string castable to int) | |
| `away_score` | int (or string castable to int) | |

### Optional fields `clean()` also recognizes

| Field | Meaning |
|---|---|
| `home_id`, `away_id` | A source's own stable id — survives a name/sponsor change, a name alone does not |
| `pool` | The rating-scale group this row belongs to, for sports whose competitions don't all meet (football divisions never play each other; tennis separates `bo3`/`bo5`) |
| `unit` | What the score counts — `goals`, `points`, `runs`, `sets`, `frames`, `maps`. Required for `model_generic.py` to answer the right kind of market; get it wrong and a points market gets priced off a distribution of sets (`CLAUDE.md`'s worked example: "total 76.5 under" at 100.00% on a 1.79 shot) |
| `surface` | Tennis-specific today (`Hard`/`Clay`/`Grass`/`Carpet`), stored but not yet used to partition rating pools — `docs/TENNIS_MODELS.md` |
| `league`, `source`, `season`, `neutral`, `extra_periods` | Passed through as-is if present; not validated |

A real stored row (tennis, sport id 4) looks like this:

```json
{"home_score": 1, "away_score": 2, "date": "2015-01-04", "home": "Alexandr Dolgopolov",
 "away": "Martin Klizan", "home_id": "D801", "away_id": "K966", "pool": "bo3",
 "unit": "sets", "surface": "Hard", "league": "Brisbane", "source": "tml",
 "season": 2015, "neutral": true}
```

### Two ways to add a row, and why one is safer

**Through `results_store.merge()` (recommended)** — this is what every adapter does, and
it's the only path that actually runs `clean()` and dedupes against what's already
stored (identity is `(date, home, away)` — `results_store.key()`):

```python
import sys; sys.path.insert(0, "/path/to/bw")
from engine import results_store

added, total = results_store.merge(1, [
    {"date": "2026-08-05", "home": "Fenerbahçe", "away": "Galatasaray",
     "home_score": 2, "away_score": 1, "unit": "goals", "source": "manual"},
])
print(added, total)
```

This is exactly what an adapter's `fn()` generator feeds into
`tools/collect_results.py --source <name>` — a manual entry is just a one-off call with
the same function.

**Editing `data/results/<sport_id>.jsonl` directly** — works, because
`results_store.load()` parses whatever JSON is on each line with no schema check at read
time. Nothing stops a malformed row from landing there this way, and nothing downstream
double-checks it: `results_store.summary()` reads `r["home"]`, `r["away"]`, `r["date"]`
unconditionally and will raise `KeyError` on a row missing one, and `merge()`'s own
dedup guard is bypassed entirely — a hand-appended duplicate `(date, home, away)` just
sits there as two rows. If you edit the file directly, match `clean()`'s field list and
check for an existing entry yourself; the `merge()` path above does both for you.

### What this is not for

`data/results/` is a record of what happened — deliberately no markets, no odds, nothing
the book said (`results_store.py`'s own module docstring: "the moment a price enters this
table it can leak into a model, and direction must never come from the price"). Don't add
a "result" for a fixture that hasn't finished, and don't estimate a score you're not sure
of — hard rule 5's "never fabricate" applies here exactly as it does to odds. A wrong row
is indistinguishable from a real one once it's inside a rating (hard rule 8), and unlike
the odds card, a bad results row doesn't get caught by a book-mismatch warning; it just
quietly changes a team's Elo.

## What this doc is and isn't

It isn't a new import format, a new flag, or a new file. `--input` and
`data/results/<sport_id>.jsonl` already do the whole job; this file exists so the answer
to "what do I do if a source is down" is a pointer here rather than a re-derivation from
source each time.
