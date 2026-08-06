# GITHUB_ACTIONS.md — every workflow, what's pre-existing vs. new

12 files in `.github/workflows/`. Ten predate this session and keep running the live
scanner exactly as they did before it (`docs/DECISIONS/0001` — this session extends the
engine, it does not touch scheduling behaviour without a stated reason). Two are new:
`combine.yml` (the football+tennis combine platform's own daily run) and `tests.yml`
(push/PR gate).

## The pre-existing scanner automation (fully unchanged, including cadence)

| Workflow | Trigger | What it does |
|---|---|---|
| **`daily.yml`** | `schedule`: `43 6,7,8 * * *` (06:43/07:43/08:43 UTC ≈ 09:43–11:43 Istanbul) + `workflow_dispatch` | The scheduled daily run — fetch, analyse, notify the daily-picks list. Untouched by this session — see "What this session tried first, then reverted" below. |
| **`results.yml`** | `schedule`: `30 * * * *` (hourly, `:30`) + `workflow_dispatch` | Grades finished selections, rebuilds `results.html`/`stats.html`, refreshes the bet-slip code. **This session added two steps here** — see below; everything else is unchanged. |
| **`watch-live.yml`** | `schedule`: `37 * * * *` (hourly) + `workflow_dispatch` | Sweeps Betwinner's own live feed for finished results across every sport the book carries — the default results source per `CLAUDE.md`. Three ~55-minute slices per firing, committing after each. |
| **`collect-results.yml`** | `schedule`: `5 */2 * * *` (every 2 hours) + `workflow_dispatch` | Table-tennis-specific results collector (Setka's live scoreboard is a rolling window, needs frequent polling). |
| **`fetch-48h.yml`** | `workflow_dispatch` only | Manual pull of the next N hours of Betwinner's pre-match card. |
| **`fetch-betwinner.yml`** | `workflow_dispatch` only | Manual pull for one tournament/champ id. |
| **`fetch-odds.yml`** | `workflow_dispatch` only | Legacy OddsPapi path, kept for comparison only. |
| **`probe-odds.yml`** | `workflow_dispatch` only | The coverage gate named in `CLAUDE.md`'s "do this FIRST". |
| **`probe-oddsapi-io.yml`** | `workflow_dispatch` only | Same question against a different provider. |
| **`heartbeat.yml`** | `schedule`: `23 9 * * *`, `23 13 * * *` + `workflow_dispatch` | "Does today have a logged list at all" — catches a scheduled run that never fired. |
| **`telegram-test.yml`** | `workflow_dispatch` only | Sends one confirmation message to verify Telegram credentials. |

## What this session tried first, then reverted: sharing `daily.yml`'s job

The first version of this work added the combine platform's build/PDF/settle/health/pages
steps directly inside `daily.yml`'s existing job, specifically to reuse its already-fetched
card and avoid a second Betwinner fetch. That worked, but it meant the combine platform
inherited `daily.yml`'s cadence (~09:43–11:43 Istanbul), not the platform brief's explicit
07:00 Europe/Istanbul requirement.

Asked directly, the operator chose the brief's stated time over preserving the fetch-
sharing optimisation. `docs/DECISIONS/0006` has the full reasoning; the practical result is
that **`daily.yml` today is byte-for-byte what it was before this session** (one comment
added noting where the combine platform's steps went) — nothing about the daily-picks
list's fetch, timing, or behaviour changed.

## New workflow: `combine.yml`

The football+tennis combine platform's complete daily run, on its **own** schedule and its
**own** fetch (not `daily.yml`'s card):

```
schedule: 43 4 * * *   (04:43 UTC = 07:43 Istanbul — primary)
          43 5 * * *   (08:43 Istanbul — backstop 1, --only-if-new)
          43 6 * * *   (09:43 Istanbul — backstop 2, --only-if-new)
workflow_dispatch: hours, dry_run (skip minting a slip code), use_committed_card
```

`:43` rather than `:00` for the same reason `daily.yml`/`watch-live.yml` already use it:
GitHub's scheduler is best-effort and drops jobs more often at exact top-of-hour minutes
(`daily.yml`'s own history: one real day, an exact `06:10` cron never fired at all).

Steps, in order: checkout → install `reportlab` → fetch its own 24h window
(`tools/fetch_window.py --hours 24 --out data/betwinner_combine.json.gz`) → build the
combine (`tools/daily_combine.py`, `--only-if-new` on the two backstop crons, non-fatal —
a failure here must not skip the settle/health/pages steps below) → render the PDF
(non-fatal) → settle any pending combines (`tools/grade_combine.py` — a same-workflow
backstop; `results.yml`'s hourly step below is the primary settlement mechanism) → check
data source health → rebuild all 14 platform pages → commit, with the same
fetch-then-restore-on-conflict retry loop `daily.yml`/`results.yml` already use, scoped to
only the files this workflow owns (`combine.json`, `combine_report.pdf`,
`data/combine_log.jsonl`, `data/proposed_changes.jsonl`, `data/source_health.json`, the 14
platform pages).

**Not yet built:** a Telegram notification for the combine (`docs/ROADMAP.md`) — today the
combine and its PDF are readable from the repo and the web pages, not pushed anywhere.

## New steps inside `results.yml` (same job, same hourly `:30` schedule — unchanged trigger)

Two steps appended after the pre-existing "Refresh the bet-slip code..." step:

1. **Settle graded combines** — `tools/grade_combine.py`, non-fatal. Same hourly reasoning
   as the pre-existing predictions grader: a leg's result is known the moment its match
   ends, not at a fixed time of day.
2. **Rebuild the combine-platform pages** — `tools/make_platform_pages.py`, non-fatal.

The Commit step's file list gained `data/combine_log.jsonl` and the 14 platform pages, and
its retry loop's re-derivation block gained `grade_combine.py` / `make_platform_pages.py`
calls alongside the pre-existing `grade_predictions.py` / `make_stats_page.py`
re-derivation. No schedule change — `results.yml` still fires on the same `:30` hourly cron
it always has.

## New file: `tests.yml`

Did not exist before this session — nothing ran the test suite on a change before it
merged.

- **Trigger:** `push` to `main`, `pull_request`, `workflow_dispatch`.
- **Steps:** compile-check every `.py` file; a minimal secret-pattern grep for a Telegram
  bot token shape that fails the build on a match outside `*.md`/`tests/*`; the full
  `unittest discover` run (both test files); install `reportlab` and re-run
  `tests.test_combine_platform.TestPdfReport`; a YAML syntax dry-parse of every workflow
  file in this directory (now 12, including itself and `combine.yml`).
- No frontend build step — every screen is Python generating self-contained HTML, and the
  unittest suite already exercises that generation directly.

See `docs/SECURITY.md` for what the secret-pattern step is and isn't a substitute for.

## The 07:00 Istanbul cadence question — resolved

Was open in an earlier draft of this document; resolved by the operator choosing to give
the combine platform its own workflow and its own fetch rather than share `daily.yml`'s
cadence. See "New workflow: `combine.yml`" above and `docs/DECISIONS/0006`.

## Required secrets

Grepped directly from the workflow files (`secrets.*` references):

| Secret | Used by | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `daily.yml`, `results.yml`, `heartbeat.yml`, `telegram-test.yml` | No — absence degrades to a skipped notification, never a failed run (`CLAUDE.md` "Secrets", `docs/SECURITY.md`) |
| `ODDSPAPI_KEY` | `fetch-odds.yml`, `probe-odds.yml` | No — legacy/comparison path only |
| `ODD_API_KEY`, `ODDS_API_KEY`, `ODDSAPI_KEY`, `ODDS_API_IO_KEY`, `ODDSAPIIO_KEY`, `ODDSAPI_IO_KEY`, `ODDS_API_TOKEN`, `ODDSAPI_TOKEN`, `ODDS_KEY`, `ODDSIO_KEY` | `probe-oddsapi-io.yml` only | No — this workflow's job is discovering which (if any) is populated |

**`combine.yml` reads no secret at all.** `tools/daily_combine.py`, `tools/grade_combine.py`,
`tools/make_pdf_report.py`, `tools/make_platform_pages.py`, `tools/check_source_health.py`
take no credentials — the combine platform's only outbound calls are to Betwinner's own
public endpoints (unauthenticated, same as the pre-existing pipeline) and to the handful of
catalogued, keyless sources `check_source_health.py` probes (`docs/DATA_SOURCES.md`).
