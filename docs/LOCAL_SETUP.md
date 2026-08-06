# LOCAL_SETUP.md — running this locally

Two products live in this repo: the original scanner/daily-picks pipeline and the
football+tennis combine platform added this session (`docs/DECISIONS/0001` — extension,
not a rewrite). Both run from the same fixture, both run with zero installs, and both are
covered below. Command lines are exact — copied from each tool's `argparse` block, not
guessed.

## Clone

```
git clone <repo-url> bw
cd bw
```

No submodules, no `.env` template to fill in — see "Secrets" below for what's optional.

## Dependencies: none, except for PDF generation

The core pipeline (`engine/`, `scan.py`, `tools/daily_report.py`,
`tools/daily_combine.py`, `tools/collect_*.py`, `tools/build_generic_model.py` and
everything they import) is **standard library only**. This isn't a claim made here first —
`tests/test_regression.py`'s own docstring states it ("Standard library only — the project
takes no pip dependencies") and the test suite is what would break if it stopped being
true. Skip `pip install` entirely unless you need a PDF.

`requirements.txt` exists for exactly one thing:

```
pip install -r requirements.txt
```

installs `reportlab` (pinned `>=4.0,<5.1`), needed only by `tools/make_pdf_report.py`.
Nothing else in the repo imports it. Running the test suite without installing it first
is fine — the PDF-dependent tests skip themselves cleanly (see "Tests" below) rather than
failing.

## The scanner (`scan.py`)

The original product: single-book, composite-score, top-N singles. Runs fully offline on
a saved JSON pull — there is no network call anywhere in this path.

```
python3 scan.py --input fixtures/sample.json
```

Flags (`scan.py`):

| Flag | Default | Meaning |
|---|---|---|
| `--input` | *(required)* | Path to a JSON or `.json.gz` odds pull |
| `--book` | `config.BOOK` (`betwinner`) | Bookmaker slug to scan |
| `--top` | `config.TOP_N` (`50`) | Rows to print/write |
| `--include-alt` | off | Include alternative lines, not just the main line |
| `--parlay` | off | Also print a top-N parlay summary (book-implied numbers only — hard rule 4) |

Writes `report.json` (`config.REPORT_PATH`) and prints the ranked table to stdout. This
is the tool the regression test (`tests/test_regression.py`) re-runs against
`fixtures/expected_report.json` on every change.

## The daily picks pipeline (`tools/daily_report.py`)

The scheduled product (`.github/workflows/daily.yml`): windows → picks → score → page →
Telegram, described in full in `CLAUDE.md`. Locally, against the committed fixture:

```
python3 tools/daily_report.py --input fixtures/sample.json --no-coupon --no-telegram
```

Both flags matter for a local run, not just convenience:

- **`--no-coupon`** skips `engine/coupon.py`'s call to Betwinner's own
  `LiveBet/Open/SaveCoupon` endpoint. Without it, this command reaches out to
  `betwinner.com` over the real network (and does so again inside `--no-coupon`-less
  `daily_combine.py` runs — see below). It fails gracefully if the network is unreachable
  (`engine/coupon.py`'s `_post()` catches the error and returns `Success: False` rather
  than raising), but it still tries, on a live host, for real.
- **`--no-telegram`** prints the notice text to stdout instead of calling
  `engine/telegram.py`. Not strictly required — a missing `TELEGRAM_BOT_TOKEN` /
  `TELEGRAM_CHAT_ID` already degrades to a no-op send rather than an error (see
  `docs/SECURITY.md`) — but it's the only way to see the notice text without either
  setting real credentials or letting a network call attempt and fail.

Other flags:

| Flag | Default | Meaning |
|---|---|---|
| `--input` | *(required)* | Betwinner feed pull, JSON or `.json.gz` |
| `--predictions-log` | `data/predictions.jsonl` | Append-only prediction log (see caveat below) |
| `--windows` | `24` (`config.DAILY_WINDOWS_HOURS`) | Comma-separated hour windows to analyse |
| `--out` | `daily_report.json` | Report JSON |
| `--page` | `picks.html` | Rendered page (built via `tools/make_picks_page.py`, called automatically — see "Web pages" below) |
| `--simulated-out` | `data/simulated_leagues.json` | Flagged simulated-fixture competitions |
| `--only-if-new` | off | Skip the run (or just the Telegram send) if today's date is already logged — the backstop-run guard `daily.yml`'s 07:43/08:43 retries pass |

### Local runs write into files the live pipeline treats as permanent

`--predictions-log`, `--out`, `--page`, and `--simulated-out` all default to paths that
are git-tracked, live-production artifacts: `data/predictions.jsonl` in particular is the
append-only log `docs/MANUAL_DATA_IMPORT.md`-adjacent grading depends on, and per
`CLAUDE.md` it is written once, at pick time, and never rewritten — a local test run
against `fixtures/sample.json` would append real rows stamped with **today's actual
wall-clock date** into that same file. Point every one of these flags at a scratch
location for a local test:

```
mkdir -p /tmp/bwtest
python3 tools/daily_report.py --input fixtures/sample.json --no-coupon --no-telegram \
  --predictions-log /tmp/bwtest/predictions.jsonl \
  --out /tmp/bwtest/daily_report.json \
  --page /tmp/bwtest/picks.html \
  --simulated-out /tmp/bwtest/simulated_leagues.json
```

If you skip this, `git status` after the run is the way back — nothing is pushed by a
local invocation, only written to the working tree.

## The daily combine pipeline (`tools/daily_combine.py`)

This session's product: one football+tennis combine a day, or an honest "none today"
(`docs/DECISIONS/0001`, `0003`). Reuses the same card-loading and model-loading code as
`daily_report.py` (`tools/daily_report.load`, `.load_models`) rather than re-fetching or
re-fitting anything.

```
python3 tools/daily_combine.py --input fixtures/sample.json --no-coupon \
  --out /tmp/bwtest/combine.json --log /tmp/bwtest/combine_log.jsonl
```

`--no-coupon` is required for an offline run for the same reason as above: without it,
this script calls `engine/coupon.py`'s `create()` against the live Betwinner slip
endpoint. `--out`/`--log` are pointed at scratch paths here too — `data/combine_log.jsonl`
is this product's equivalent of `predictions.jsonl` (one immutable row per day, selection
fields never rewritten after the fact — see `tools/daily_combine.py`'s `log_combine()`
docstring).

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--input` | *(required)* | Betwinner feed pull, JSON or `.json.gz` |
| `--hours` | `24.0` (`config.DAILY_WINDOWS_HOURS[0]`) | Window to draw candidates from |
| `--out` | `combine.json` | Combine report JSON, consumed by `make_pdf_report.py` and `make_platform_pages.py` |
| `--log` | `data/combine_log.jsonl` | Immutable one-row-per-day log |
| `--no-coupon` | off | Skip minting a bet-slip code |
| `--only-if-new` | off | Skip entirely if today's combine is already logged |

On `fixtures/sample.json` (49 raw fixtures, a Conference League slice), expect the
combine to legitimately come back empty (`"neden": "..."` in the output) far more often
than the daily-picks list does — `config.MIN_COMBINE_CONFIDENCE = 80.0` is a second,
stricter, additive floor on top of the existing `MIN_MODEL_SURVIVAL = 0.75`
(`docs/DECISIONS/0003`), and a small fixture has few football/tennis candidates to begin
with (`config.COMBINE_SPORTS = {1, 4}`).

## Tests

```
python3 -m unittest discover -s tests -v
```

Two files, deliberately separate (`tests/test_combine_platform.py`'s own docstring):

- **`tests/test_regression.py`** — anchors the live scan/daily-picks pipeline against
  `fixtures/expected_report.json`. Regenerating the snapshot is a deliberate act, not a
  side effect of a passing run:
  ```
  python3 tests/test_regression.py --update
  ```
  Read the diff before committing a regenerated snapshot — this file is what would catch
  an unintended change to the live pipeline's output.
- **`tests/test_combine_platform.py`** — the new platform's engine layer
  (`engine/dataquality.py`, `engine/confidence.py`, `engine/referee.py`,
  `engine/combine.py`, `engine/governance.py`), against synthetic fixtures, not the
  sample card. Kept in its own file so a failure here never reads as a failure in the
  live pipeline's own suite, or vice versa.

`TestPdfReport` inside `test_combine_platform.py` calls `unittest.SkipTest` in
`setUpClass` if `reportlab` isn't importable, so the full discovery command above passes
with zero installs — it just skips those cases. Install `requirements.txt` first to
actually exercise them:

```
pip install -r requirements.txt
python3 -m unittest tests.test_combine_platform.TestPdfReport -v
```

This mirrors `.github/workflows/tests.yml` exactly — see `docs/GITHUB_ACTIONS.md`.

## Web pages

Two independent code paths, deliberately not merged (`tools/webshell.py`'s own
docstring, `docs/DECISIONS/0001`):

- **`picks.html` / `results.html`** are built by `tools/make_picks_page.py`, called
  automatically from inside `tools/daily_report.py` (`--page`) and
  `tools/daily_results.py` (`--out`) respectively. There's no reason to invoke
  `make_picks_page.py` directly for a normal local run:
  ```
  python3 tools/make_picks_page.py --report daily_report.json --out picks.html
  ```
  (`--report` defaults to `daily_report.json`, `--out` to `picks.html` — useful only if
  you already have a report JSON on disk and want to re-render just the page.)

- **The 14 combine-platform screens** are rendered standalone, in one pass, from
  whatever data already exists on disk:
  ```
  python3 tools/make_platform_pages.py
  ```
  | Flag | Default |
  |---|---|
  | `--combine` | `combine.json` |
  | `--combine-log` | `data/combine_log.jsonl` |
  | `--source-health` | `data/source_health.json` |
  | `--watch-log` | `data/watch_log.jsonl` |
  | `--out-dir` | `.` |

  Missing inputs degrade to an explicit empty state per page rather than an error — run
  it against an empty checkout and it still writes all 14 files
  (`combine.html`, `referee.html`, `dataquality.html`, `scanned.html`, `rejected.html`,
  `combine_history.html`, `combine_results.html`, `lab.html`, `calibration.html`,
  `model_versions.html`, `proposed_changes.html`, `source_health.html`, `runs.html`,
  `settings.html`). Point `--out-dir` at a scratch directory locally for the same reason
  as above: the defaults land on files `daily.yml`/`results.yml` also write.

## Generating a PDF

```
pip install -r requirements.txt
python3 tools/make_pdf_report.py --input combine.json --out combine_report.pdf
```

`--input` defaults to `combine.json`, `--out` to `combine_report.pdf`. Requires a
`combine.json` on disk first (run `daily_combine.py` above); the tool exits with an
error naming that if the input file doesn't exist. Renders both outcomes explicitly — a
produced combine gets the full per-selection breakdown, an empty day gets an honest
explanation of why, using the vendored DejaVu Sans font (`assets/fonts/`) rather than
reportlab's built-in Helvetica, which is missing `ğ`/`ı`/`ş` and would silently mangle
Turkish text.

## The results / model loop (touches the network)

Unlike everything above, these four tools are not fixture-only — they fetch from real,
named external sources or need results already collected to do anything useful. Listed
here for completeness since their flags were asked for, not because a local run needs
them to exercise the daily-picks or combine pipeline against the fixture.

**`tools/collect_results.py`** — one HTTP-fetching adapter per source, all sharing
`engine/results_store.py`'s schema (see `docs/MANUAL_DATA_IMPORT.md` for the schema
itself and for supplying results without any of this).

```
python3 tools/collect_results.py --list                 # adapters + what's already stored
python3 tools/collect_results.py --all                   # every adapter
python3 tools/collect_results.py --source tml             # one adapter
python3 tools/collect_results.py --source tml --restate   # re-derive that adapter's own rows in place
```

| Flag | Meaning |
|---|---|
| `--source NAME` | Run one adapter (`football`, `euroleague`, `tml`, `tennisexplorer`, `mlb`, `setka`) |
| `--all` | Run every adapter |
| `--list` | Print adapters and current `data/results/` coverage, fetches nothing |
| `--restate` | Re-apply the named adapter's current field set to rows it already wrote, without re-deriving scores (see the tool's own docstring for why this exists — an adapter learning to declare a new field, e.g. `surface`) |

**`tools/build_generic_model.py`** — local only, no network. Fits from whatever is
already in `data/results/<sport>.jsonl`.

```
python3 tools/build_generic_model.py --sport 4
python3 tools/build_generic_model.py --all
```

`--sport <id>` fits one sport; omitting it (`--all` is the documented spelling) fits
every sport currently in the store and prints which came back `KULLANILABİLİR`
(usable) versus refused, per hard rule 8's calibration gate.

**`tools/grade_predictions.py`** — checks the results store first (local, no network);
falls back to fetching `football-data.co.uk` season CSVs and a flashscore feed only for
football predictions the store hasn't resolved.

```
python3 tools/grade_predictions.py
```

| Flag | Default | Meaning |
|---|---|---|
| `--predictions` | `data/predictions.jsonl` | Log to grade |
| `--out` | `data/scoreboard.json` | Aggregate scoreboard |
| `--season` | `2526` | football-data.co.uk season code for the CSV fallback |
| `--flashscore-days` | `4` | Days of the flashscore feed to read for football fallback |

**`tools/daily_results.py`** — local only (reads the prediction log, rebuilds a page);
Telegram send is the only network call, and it's skippable.

```
python3 tools/daily_results.py --out /tmp/bwtest/results.html --no-telegram
python3 tools/daily_results.py --date 2026-07-26 --no-telegram
```

| Flag | Default | Meaning |
|---|---|---|
| `--predictions` | `data/predictions.jsonl` | Log to read |
| `--date` | *(blank = most recent logged day)* | `YYYY-MM-DD` |
| `--out` | `results.html` | Rendered scorecard |
| `--state` | `data/results_sent.json` | Notification-dedup state |
| `--no-telegram` | off | Skip the send |
| `--force-send` | off | Notify even when nothing new settled |

**`tools/grade_combine.py`** — the combine platform's equivalent of
`grade_predictions.py`. No flags at all; reads and rewrites `data/combine_log.jsonl` in
place.

```
python3 tools/grade_combine.py
```

## Diagnostics: source health (touches the network)

```
python3 tools/check_source_health.py
```

No flags. Probes the six catalogued sources in `docs/DATA_SOURCES.md` plus Betwinner's
own mirror resolution, and writes `data/source_health.json` (rendered on the
**Veri Kaynağı Sağliği** screen). Every probe is qualified on response body, not status
code (hard rule 10) and is best-effort — a network failure here marks that one source
`unavailable`/`degraded` and never raises, but the command itself does reach six real
external hosts plus Betwinner.

## Secrets

Nothing above requires a secret to run. `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` enable
notifications and degrade to a clean no-op without them (`CLAUDE.md`'s "Secrets" section,
`docs/SECURITY.md`). `ODDSPAPI_KEY` is only read by the legacy `fetch-odds.yml`/
`probe-odds.yml` workflows, not by anything in "how to run locally" above — the live
pipeline reads Betwinner's own feed directly (`engine/bwfeed.py`), no key needed.
