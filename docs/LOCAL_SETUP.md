# LOCAL_SETUP.md — running this locally

One product lives in this repo today: the football+tennis daily combine platform. An
earlier, second product — a multi-sport top-N scanner and its own daily-picks pipeline —
was retired outright (`docs/DECISIONS/0007`); this document no longer covers it. What
remains runs from the same fixture and with zero installs, covered below. Command lines
are exact — copied from each tool's `argparse` block, not guessed.

## Clone

```
git clone <repo-url> bw
cd bw
```

No submodules, no `.env` template to fill in — see "Secrets" below for what's optional.

## Dependencies: none, except for PDF generation

The core pipeline (`engine/`, `tools/daily_combine.py`, `tools/collect_*.py`,
`tools/build_generic_model.py` and everything they import) is **standard library only**.
This isn't a claim made here first —
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

## The daily combine pipeline (`tools/daily_combine.py`)

The product: one football+tennis combine a day, or an honest "none today"
(`docs/DECISIONS/0001`, `0003`, `0007`). Its card-loading and model-loading helpers
(`load()`, `within()`, `load_models()`) live directly inside `daily_combine.py` itself —
they used to be shared with the now-retired scanner's own daily-picks tool via a separate
module, and were folded in here once that tool was deleted and `daily_combine.py` became
the only caller (`docs/ARCHITECTURE.md`).

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

- **`tests/test_regression.py`** — regression + integration tests for the combine
  platform's shared engine (`engine/bwfeed.py`, `coupon.py`, `grade.py`, `ladder.py`,
  `mirror.py`, `model_generic.py`, `parlay.py`, `pick.py`, `rating.py`,
  `results_store.py`, `settlement.py`, `signals.py`, `simulated.py`, `telegram.py`, plus
  `tools/collect_live.py`, `grade_predictions.py`, `heartbeat.py`, `refresh_combine.py`),
  run directly against `fixtures/sample.json`. Previously anchored the now-retired
  scanner's output against a committed snapshot (`fixtures/expected_report.json`,
  regenerated with a `--update` flag); both the snapshot file and that mode were removed
  with the scanner (`docs/DECISIONS/0007`) — this file tests the surviving pipeline
  directly rather than by snapshot comparison.
- **`tests/test_combine_platform.py`** — the platform's engine layer
  (`engine/dataquality.py`, `engine/confidence.py`, `engine/referee.py`,
  `engine/combine.py`, `engine/governance.py`), against synthetic fixtures, not the
  sample card. Kept in its own file so a failure here never reads as a failure in the
  other file's own suite, or vice versa.

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

The 14 combine-platform screens are rendered standalone, in one pass, from whatever data
already exists on disk, through one shared shell (`tools/webshell.py`):

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
as above: the defaults land on files `combine.yml`/`results.yml` also write.

The retired scanner used to render a second, independent set of pages (`picks.html`,
`results.html`, via `tools/make_picks_page.py`) through its own separate escaping path,
kept apart from `webshell.py` on purpose while both products were live
(`docs/DECISIONS/0001`). That tool and those pages were deleted with the scanner
(`docs/DECISIONS/0007`) — `make_platform_pages.py`/`webshell.py` is the only page-rendering
path left.

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

Unlike everything above, these tools are not fixture-only — they fetch from real,
named external sources or need results already collected to do anything useful. Listed
here for completeness since their flags were asked for, not because a local run needs
them to exercise the combine pipeline against the fixture.

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
| `--source NAME` | Run one adapter (`football`, `tml`, `tennisexplorer` — narrowed from six, including `euroleague`/`mlb`/`setka`, when scope fixed at football+tennis, `docs/DECISIONS/0007`) |
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
football predictions the store hasn't resolved. No scheduled workflow invokes it as a
script any more — the retired scanner's own daily-picks pipeline was its main caller
(`docs/DECISIONS/0007`) — but `tools/grade_combine.py` still imports its lookup tables
(`docs/ARCHITECTURE.md`), and it remains runnable standalone against the historical
`data/predictions.jsonl` log.

```
python3 tools/grade_predictions.py
```

| Flag | Default | Meaning |
|---|---|---|
| `--predictions` | `data/predictions.jsonl` | Log to grade |
| `--out` | `data/scoreboard.json` | Aggregate scoreboard |
| `--season` | `2526` | football-data.co.uk season code for the CSV fallback |
| `--flashscore-days` | `4` | Days of the flashscore feed to read for football fallback |

**`tools/grade_combine.py`** — the combine platform's own settlement tool, reusing
`grade_predictions.py`'s lookup tables rather than duplicating them. No flags at all;
reads and rewrites `data/combine_log.jsonl` in place.

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
