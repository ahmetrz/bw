# GITHUB_ACTIONS.md — every workflow, what's pre-existing vs. new

11 files in `.github/workflows/`. Ten predate this session and keep running the live
scanner exactly as they did before it (`docs/DECISIONS/0001` — this session extends the
engine, it does not touch scheduling behaviour without a stated reason). One
(`tests.yml`) is new. The combine platform's own automation is not a twelfth file — it is
new steps inside two of the existing ten. That distinction is deliberate and is the main
thing this document exists to make unambiguous.

## The pre-existing scanner automation (unchanged cadence)

| Workflow | Trigger | What it does |
|---|---|---|
| **`daily.yml`** | `schedule`: `43 6,7,8 * * *` (06:43/07:43/08:43 UTC) + `workflow_dispatch` | The scheduled daily run — fetch, analyse, notify. See its own section below; this session added steps inside it. |
| **`results.yml`** | `schedule`: `30 * * * *` (hourly, `:30`) + `workflow_dispatch` | Grades finished selections, rebuilds `results.html`/`stats.html`, refreshes the bet-slip code. This session added steps inside it too. |
| **`watch-live.yml`** | `schedule`: `37 * * * *` (hourly) + `workflow_dispatch` | Sweeps Betwinner's own live feed for finished results across every sport the book carries — the default results source per `CLAUDE.md`. Runs three ~55-minute slices per firing, committing after each, so a mid-run failure loses at most one slice. |
| **`collect-results.yml`** | `schedule`: `5 */2 * * *` (every 2 hours) + `workflow_dispatch` | Table-tennis-specific results collector (Setka's live scoreboard is a rolling ~19-match window, not an archive — needs frequent polling to accumulate anything). |
| **`fetch-48h.yml`** | `workflow_dispatch` only | Manual pull of the next N hours of Betwinner's pre-match card, no API key. No schedule — a cron here would spend quota without operator approval (CLAUDE.md HITL gate 5). |
| **`fetch-betwinner.yml`** | `workflow_dispatch` only | Manual pull for one tournament/champ id via Betwinner's own feed, with sub-game discovery. No schedule, same reason as above. |
| **`fetch-odds.yml`** | `workflow_dispatch` only (schedule removed — see the file's own comment) | The legacy OddsPapi path. Kept only for re-testing or comparison; the live pipeline reads Betwinner's own feed directly instead (`fetch-betwinner.yml`/`fetch_window.py`). |
| **`probe-odds.yml`** | `workflow_dispatch` only | The coverage gate named in `CLAUDE.md`'s "do this FIRST": confirms which bookmaker slug an OddsPapi key actually returns, logging the real returned book against the requested one. |
| **`probe-oddsapi-io.yml`** | `workflow_dispatch` only | Same question against a different provider (odds-api.io, not OddsPapi) — sweeps a list of plausible secret names to find which one, if any, is populated, without ever printing a value. |
| **`heartbeat.yml`** | `schedule`: `23 9 * * *`, `23 13 * * *` + `workflow_dispatch` | Asks "does today have a logged list at all" from outside `daily.yml`'s own schedule — catches the case where the scheduled run never fired, which produces no error of its own. At most one alert a day. |
| **`telegram-test.yml`** | `workflow_dispatch` only | Sends one confirmation message to verify `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` without waiting on a full run. |

## What this session added

### New steps inside `daily.yml` (same job, same schedule, same fetched card)

`daily.yml`'s job already fetched the card, ran `tools/daily_report.py`, refreshed the
results store, graded predictions, and built `method.html` before this session. Six new
steps were appended to the **same job**, after "Analyse and notify" and before "Commit":

1. **Install PDF dependencies** — `pip install --quiet -r requirements.txt`, needed for
   the step below.
2. **Build the football+tennis combine** — `tools/daily_combine.py --input
   data/betwinner_daily.json.gz --out combine.json --log data/combine_log.jsonl`. Reads
   the file the earlier "Fetch 48h window" / "Use committed card" step already wrote —
   **this is not a second Betwinner fetch**. Carries `--only-if-new` on the same
   07:43/08:43 backstop condition `daily_report.py` already uses.
3. **Render the combine PDF report** — `tools/make_pdf_report.py --input combine.json
   --out combine_report.pdf`, non-fatal on failure (`|| echo`).
4. *(pre-existing, unchanged: "Refresh the results store and rebuild every model",
   "Grade yesterday's predictions", "Build the method page")*
5. **Settle graded combines** — `tools/grade_combine.py`, non-fatal.
6. **Check data source health** — `tools/check_source_health.py`, non-fatal; writes
   `data/source_health.json`.
7. **Build the combine-platform pages** — `tools/make_platform_pages.py`, non-fatal;
   writes all 14 new screens.

The **Commit** step's file list was extended to match: `combine.json`,
`combine_report.pdf`, `data/combine_log.jsonl`, `data/proposed_changes.jsonl`,
`data/source_health.json`, and the 14 platform pages
(`combine.html referee.html dataquality.html scanned.html rejected.html
combine_history.html combine_results.html lab.html calibration.html model_versions.html
proposed_changes.html source_health.html runs.html settings.html`) are added and, on a
push conflict, restored from `/tmp/bwdaily` in the same rebase-retry loop the pre-existing
files (`daily_report.json`, `picks.html`, `data/predictions.jsonl`, ...) already used —
no new concurrency mechanism was introduced, the existing one was widened.

### New steps inside `results.yml` (same job, same hourly schedule)

Two steps appended after the pre-existing "Refresh the bet-slip code..." step:

1. **Settle graded combines** — `tools/grade_combine.py`, non-fatal. Same hourly
   reasoning as the pre-existing predictions grader: a leg's result is known the moment
   its match ends, not at a fixed time of day.
2. **Rebuild the combine-platform pages** — `tools/make_platform_pages.py`, non-fatal.

The **Commit** step's file list gained `data/combine_log.jsonl` and the same 14 platform
pages, and its retry loop's re-derivation block gained `grade_combine.py` and
`make_platform_pages.py` calls alongside the pre-existing `grade_predictions.py` /
`make_stats_page.py` re-derivation.

**Neither `daily.yml` nor `results.yml` is a new workflow file.** No new schedule was
created, no new job, no second fetch of the Betwinner card. The combine platform rides
inside jobs that already existed, on cadences the operator already approved.

### New file: `tests.yml`

Did not exist before this session — nothing ran the test suite on a change before it
merged; `daily.yml`/`results.yml`/`watch-live.yml` run the pipeline, not its tests.

- **Trigger:** `push` to `main`, `pull_request`, `workflow_dispatch`.
- **Steps:** compile-check every `.py` file (`python3 -m py_compile`, catches a syntax
  error before it reaches a scheduled job); a minimal secret-pattern grep for a Telegram
  bot token shape (`[0-9]{6,10}:[A-Za-z0-9_-]{35}`) that fails the build if it matches
  anything outside `*.md`/`tests/*`; the full `unittest discover` run (both test files);
  install `reportlab` and re-run `tests.test_combine_platform.TestPdfReport`
  specifically; a YAML syntax dry-parse of every workflow file in this directory.
- No frontend build step — every screen is Python generating self-contained HTML, and
  the unittest suite already exercises that generation directly.

See `docs/SECURITY.md` for what the secret-pattern step is and isn't a substitute for.

## Open item: the 07:00 Istanbul cadence question (not resolved here)

The platform brief asks for the daily combine to run at 07:00 Europe/Istanbul.
`daily.yml`'s existing cron — `43 6,7,8 * * *` UTC — lands at roughly **09:43 / 10:43 /
11:43 Istanbul**, not 07:00. That schedule is the one `CLAUDE.md` records as
operator-approved under HITL gate 5, and it predates this session.

This session did **not** change it. Reusing the existing job (rather than adding a
competing schedule) means the combine platform necessarily inherited the existing
trigger time along with everything else it reuses — and changing an already-approved
cadence needs the same approval gate that set it, not a unilateral edit made in passing
while wiring in an unrelated feature. So today: the combine is built and sent at the same
time the daily picks list always has been, not at 07:00 Istanbul. Left open, tracked in
`docs/ROADMAP.md`, for the operator to decide — earlier cron, a second scheduled firing,
or accepting the current time as good enough.

## Required secrets

Grepped directly from the workflow files (`secrets.*` references):

| Secret | Used by | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `daily.yml`, `results.yml`, `heartbeat.yml`, `telegram-test.yml` | No — absence degrades to a skipped notification, never a failed run (`CLAUDE.md` "Secrets", `docs/SECURITY.md`) |
| `ODDSPAPI_KEY` | `fetch-odds.yml`, `probe-odds.yml` | No — only the legacy/comparison OddsPapi path; the live pipeline doesn't read it |
| `ODD_API_KEY`, `ODDS_API_KEY`, `ODDSAPI_KEY`, `ODDS_API_IO_KEY`, `ODDSAPIIO_KEY`, `ODDSAPI_IO_KEY`, `ODDS_API_TOKEN`, `ODDSAPI_TOKEN`, `ODDS_KEY`, `ODDSIO_KEY` | `probe-oddsapi-io.yml` only | No — this workflow's whole job is discovering which (if any) of these plausible names is actually populated; it is itself a probe, not a consumer of a known secret |

**Nothing this session added reads a secret.** `tools/daily_combine.py`,
`tools/grade_combine.py`, `tools/make_pdf_report.py`, `tools/make_platform_pages.py`, and
`tools/check_source_health.py` take no credentials at all — the combine platform's only
outbound calls are to Betwinner's own public endpoints (already unauthenticated, same as
the pre-existing pipeline) and to the handful of catalogued, keyless sources
`check_source_health.py` probes (`docs/DATA_SOURCES.md`).
