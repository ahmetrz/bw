# GITHUB_ACTIONS.md — every workflow, what it does today

11 files in `.github/workflows/`. `docs/DECISIONS/0007` retired the two workflows that used
to run the old multi-sport scanner and its daily picks list (`daily.yml`,
`collect-results.yml`) — deleted outright, not kept disabled. `combine.yml` is the
platform's only daily driver today; the rest are either its supporting hourly/diagnostic
jobs or `workflow_dispatch`-only tools the retirement did not touch.

## The workflows that make up the product

| Workflow | Trigger | What it does |
|---|---|---|
| **`combine.yml`** | `schedule`: `43 4,5,6 * * *` (04:43/05:43/06:43 UTC = 07:43/08:43/09:43 Istanbul) + `workflow_dispatch` | The platform's entire daily run — own fetch, builds the combine, renders the PDF, notifies Telegram, refreshes the football/tennis results store and models, settles pending combines, checks source health, rebuilds all 14 pages. See below. |
| **`results.yml`** | `schedule`: `30 * * * *` (hourly, `:30`) + `workflow_dispatch` | Settles finished legs (`tools/grade_combine.py`), refreshes the bet-slip code from legs that have not started (`tools/refresh_combine.py`), rebuilds the 14 platform pages. No longer touches `data/predictions.jsonl`/`results.html`/`stats.html`/`picks.html` — those steps and the code behind them were deleted with the scanner. |
| **`watch-live.yml`** | `schedule`: `37 * * * *` (hourly) + `workflow_dispatch` | Sweeps Betwinner's own live feed for finished football and tennis results. Mechanics unchanged; its scope narrowed automatically because `tools/collect_live.py`'s watch list (`SPORTS`) is now football+tennis only (`docs/DECISIONS/0007`), and its own header comment was rewritten to describe that fixed two-sport reality — including the measured per-sport volume from when it watched roughly thirty — rather than present it as still current. Three ~55-minute slices per firing, committing after each. |
| **`heartbeat.yml`** | `schedule`: `23 9 * * *`, `23 13 * * *` + `workflow_dispatch` | "Does today have a combine at all" — catches a scheduled `combine.yml` run that never fired. Retargeted from `data/predictions.jsonl` to `data/combine_log.jsonl` (one row per day, written even when the combine comes back empty) — same watchdog mechanism, new file, since the daily-picks log it used to watch no longer exists. |

## Diagnostic / manual-only workflows (not touched by the retirement)

| Workflow | Trigger | What it does |
|---|---|---|
| **`fetch-48h.yml`** | `workflow_dispatch` only | Manual pull of the next N hours of Betwinner's pre-match card. |
| **`fetch-betwinner.yml`** | `workflow_dispatch` only | Manual pull for one tournament/champ id. |
| **`fetch-odds.yml`** | `workflow_dispatch` only | Legacy OddsPapi path, kept for comparison only. |
| **`probe-odds.yml`** | `workflow_dispatch` only | The coverage gate named in `CLAUDE.md`'s "do this FIRST". |
| **`probe-oddsapi-io.yml`** | `workflow_dispatch` only | Same question against a different provider. |
| **`telegram-test.yml`** | `workflow_dispatch` only | Sends one confirmation message to verify Telegram credentials. |

None of these six are scanner- or daily-picks-specific, so `docs/DECISIONS/0007` had no
reason to touch them — they are exactly as they were before the retirement.

## `combine.yml`, step by step

The football+tennis combine platform's complete daily run, on its own schedule and its own
fetch:

```
schedule: 43 4 * * *   (04:43 UTC = 07:43 Istanbul — primary)
          43 5 * * *   (08:43 Istanbul — backstop 1, --only-if-new)
          43 6 * * *   (09:43 Istanbul — backstop 2, --only-if-new)
workflow_dispatch: hours, dry_run (skip minting a slip code), use_committed_card
```

`:43` rather than `:00` for the same reason `watch-live.yml` already uses it: GitHub's
scheduler is best-effort and drops jobs more often at exact top-of-hour minutes.

Steps, in order:

1. Checkout.
2. **Check Telegram credentials** (`tools/telegram_ping.py --quiet`) — fails fast on a
   present-but-broken token, before the expensive fetch; a missing token is fine and the
   run continues.
3. Install the `reportlab` PDF dependency.
4. **Fetch its own 24h window** (`tools/fetch_window.py --hours 24 --partner 159 ...
   --out data/betwinner_combine.json.gz`), or copy the committed card instead if
   `use_committed_card` was set.
5. **Build the combine** (`tools/daily_combine.py`, `--only-if-new` on the two backstop
   crons, non-fatal — a failure here must not skip the steps below).
6. **Render the PDF report** (non-fatal).
7. **Notify Telegram** (`tools/notify_combine.py --input combine.json --pdf
   combine_report.pdf`, non-fatal) — sends the PDF as an attachment with a short caption to
   the existing bot/channel; no new secret, no second bot.
8. **Refresh the results store and rebuild the football/tennis models** —
   `tools/collect_results.py --all`, then `tools/build_generic_model.py --sport 1` and
   `--sport 4` explicitly (not `--all`, since the results store may still hold other
   sports' historical rows from before scope narrowed) — replaces the old daily job's
   `--all` refit, scoped to the two sports this product actually uses.
9. **Settle graded combines** (`tools/grade_combine.py`) — a same-workflow backstop;
   `results.yml`'s hourly step is the primary settlement mechanism.
10. **Check data source health** (`tools/check_source_health.py`).
11. **Build the combine-platform pages** (`tools/make_platform_pages.py`).
12. **Commit**, with a fetch-then-restore-on-conflict retry loop scoped to only the files
    this workflow owns (`combine.json`, `combine_report.pdf`, `data/combine_log.jsonl`,
    `data/proposed_changes.jsonl`, `data/source_health.json`, `data/results`,
    `data/models`, the 14 platform pages) — `data/results`/`data/models` are rewritten
    whole rather than merged line-by-line on conflict, so a clash there takes the remote
    version and lets the next scheduled refresh regenerate them, rather than attempting a
    line-based merge (`docs/TROUBLESHOOTING.md`).

Every step from "Notify Telegram" onward is non-fatal (`|| echo "..."`) — a failure
building the combine itself, or sending it, must never skip settling yesterday's legs,
checking source health, or rebuilding the pages.

## New steps inside `results.yml` — same job, same hourly `:30` schedule

1. **Settle graded combines** — `tools/grade_combine.py`, non-fatal. A leg's result is
   known the moment its match ends, not at a fixed time of day.
2. **Refresh the bet-slip code** — `tools/refresh_combine.py --input combine.json`,
   non-fatal. Rebuilds `combine.json`'s coupon fields from legs that have not started yet
   — a slip is a live object, not a document (`CLAUDE.md`'s coupon section).
3. **Rebuild the combine-platform pages** — `tools/make_platform_pages.py`, non-fatal.

The Commit step's file list is `combine.json`, `data/combine_log.jsonl`, and the 14
platform pages. Its retry loop re-derives by re-running `grade_combine.py`,
`refresh_combine.py --input combine.json`, and `make_platform_pages.py` in sequence — all
three are pure re-derivations from what is already committed, carrying no new information,
which is why re-running them after a lost push is safe.

## `tests.yml`

Push/PR gate. Runs the test suite on every change before it merges.

- **Trigger:** `push` to `main`, `pull_request`, `workflow_dispatch`.
- **Steps:** compile-check every `.py` file; a minimal secret-pattern grep for a Telegram
  bot token shape that fails the build on a match outside `*.md`/`tests/*`; the full
  `unittest discover` run (both test files); install `reportlab` and re-run
  `tests.test_combine_platform.TestPdfReport`; a YAML syntax dry-parse of every workflow
  file in this directory (11, including itself).
- No frontend build step — every screen is Python generating self-contained HTML, and the
  unittest suite already exercises that generation directly.

See `docs/SECURITY.md` for what the secret-pattern step is and isn't a substitute for.

## Required secrets

Grepped directly from the workflow files (`secrets.*` references):

| Secret | Used by | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `combine.yml`, `heartbeat.yml`, `telegram-test.yml` | No — absence degrades to a skipped notification, never a failed run (`CLAUDE.md` "Secrets", `docs/SECURITY.md`) |
| `ODDSPAPI_KEY` | `fetch-odds.yml`, `probe-odds.yml` | No — legacy/comparison path only |
| `ODD_API_KEY`, `ODDS_API_KEY`, `ODDSAPI_KEY`, `ODDS_API_IO_KEY`, `ODDSAPIIO_KEY`, `ODDSAPI_IO_KEY`, `ODDS_API_TOKEN`, `ODDSAPI_TOKEN`, `ODDS_KEY`, `ODDSIO_KEY` | `probe-oddsapi-io.yml` only | No — this workflow's job is discovering which (if any) is populated |

**`combine.yml` reads `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`** (for the credential
pre-check and the Telegram-notify step) — reusing the exact bot and channel
`heartbeat.yml`/`telegram-test.yml` already used; no second bot was set up
(`docs/DECISIONS/0007`). `results.yml`, `watch-live.yml` and `tests.yml` read no secret at
all.
