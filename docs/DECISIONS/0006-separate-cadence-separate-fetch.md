# ADR 0006 — The combine platform gets its own workflow, own cadence, own fetch

**Date:** 2026-08-06
**Status:** Accepted (supersedes the cadence portion of ADR 0001)

## Context

ADR 0001 integrated the combine platform's daily build into the existing `daily.yml` job,
specifically to reuse its already-fetched card and avoid a second Betwinner fetch. That
meant the combine platform inherited `daily.yml`'s existing, operator-approved cron
(06:43/07:43/08:43 UTC ≈ 09:43–11:43 Istanbul) rather than the platform brief's explicit
"Türkiye saatiyle 07:00" requirement — flagged plainly in the first delivered report as an
open item, with two options: change the shared cron (moving the pre-existing daily-picks
list too) or give the combine platform its own workflow and fetch.

The operator answered directly: prioritise the brief's stated 07:00 Istanbul time over
preserving the fetch-sharing optimisation, "eski bilgiyi unut" (the previously-approved
cadence does not carry over to this new product by default — it was approved for a
different product's needs).

## Decision

- `tools/daily_combine.py`, PDF rendering, and the platform's own settle/health-check/
  page-build backstop steps move OUT of `daily.yml` into a new, standalone
  `.github/workflows/combine.yml`.
- `combine.yml` fetches its own 24-hour window (`tools/fetch_window.py --hours 24`) —
  a second daily Betwinner fetch, accepted deliberately. This is not a violation of "don't
  re-download the same data" so much as two genuinely different products each fetching
  once a day for their own, now-different, run times; the brief's don't-be-wasteful
  principle is about avoiding pointless repetition within one purpose, not about merging
  two purposes with different timing requirements into one fetch at the cost of missing an
  explicit requirement. GitHub Actions minutes are confirmed unlimited on this public repo
  (`docs/DATA_SOURCES.md`), so the actual cost of a second fetch is a second daily request
  to Betwinner's feed — not a quota problem.
- `daily.yml` reverts to exactly its pre-session shape: the daily-picks list's cadence,
  fetch, and behaviour are completely unaffected by this session's work.
- `results.yml`'s hourly `grade_combine.py` + `make_platform_pages.py` steps (added this
  session) are UNCHANGED — settlement stays hourly regardless of which workflow built the
  combine, for the same reason the existing hourly settlement loop exists at all (a bet's
  outcome is known when it ends, not the next morning).

## Cadence chosen

`combine.yml`: primary `43 4 * * *` (04:43 UTC = 07:43 Istanbul), backstops `43 5 * * *` /
`43 6 * * *` (08:43 / 09:43 Istanbul) with `--only-if-new`, mirroring exactly the reasoning
already validated in this repo for `daily.yml`/`watch-live.yml`: GitHub's scheduler runs on
a best-effort basis and drops jobs more often at exact top-of-hour minutes (`daily.yml`'s
own history: an exact `06:10` cron failed to fire at all on one real day); `:43` was
already the empirically-chosen safe offset for the existing daily job, reused here rather
than re-deriving a new one. 43 minutes past 07:00 is an accepted drift for the same
reliability reason the existing system already accepted a similar drift (09:10 → 09:43).

## Consequences

- Two Betwinner fetches a day for pre-match data instead of one (`daily.yml`'s ~09:43
  Istanbul fetch, `combine.yml`'s ~07:43 Istanbul fetch), plus the live watcher's ongoing
  result sweeps (unrelated, already hourly).
- The daily-picks list (Product 1) and the combine (Product 2) can now legitimately see
  slightly different cards (different fetch times → different odds, possibly different
  fixtures newly inside/outside the 24h window) — already true in spirit since they are
  different products with different scope (all sports vs. football+tennis only), and now
  also true in fetch timing. Not treated as a bug: nothing about this platform claims the
  two products describe the same instant.
- `combine.yml` needs its own "Check Telegram credentials"-equivalent reasoning if a
  Telegram notification for the combine is ever added (not built this session — the
  combine platform does not send Telegram messages yet, see `docs/ROADMAP.md`).
