# Betwinner Odds Scanner

A **single-book** scanner. It pulls every open market on Betwinner across the
tournaments you configure, scores each selection by a **combination** of criteria
(within-book margin, limit/liquidity, odds-range fit), ranks them, and returns the
**top 50**. No reference book. No "value vs sharp" claim. It surfaces the selections
where Betwinner treats you least badly, on its own numbers.

It emits a report. It does not place bets.

## ⚠️ STATUS — read before running
As of setup, **Betwinner coverage on your OddsPapi key is UNCONFIRMED**. Every pull
during design returned a different book (22bet) from browser cache. The API does not
silently fall back, so this needs a clean server-side test.

**Step 0 is the probe.** Do not trust `scan.py` output until the probe confirms
Betwinner actually returns. `scan.py` prints a loud warning if the data you load does
not contain Betwinner.

## How it runs (company machine blocks the site — GitHub Actions does the fetching)
1. Add repo secret `ODDSPAPI_KEY` (Settings → Secrets and variables → Actions).
2. **Probe:** Actions → `probe-odds` → Run workflow → tournament `34480`.
   Read the log: it prints the requested book, the **book actually returned**, the
   HTTP code, and the fixture count. This settles coverage definitively.
3. If confirmed: **Fetch:** Actions → `fetch-odds` → Run workflow. It writes
   `data/betwinner_<id>.json` to the repo.
4. Save one clean pull as `fixtures/sample.json` (regression anchor).
5. Run the scanner: `python scan.py --input fixtures/sample.json`.

## Repo map
```
scan.py                entrypoint: parse → filter → score → rank → top-N → report
engine/parser.py       OddsPapi response → normalized selection rows (book-agnostic)
engine/score.py        hard filters + composite score (margin / limit / range)
engine/report.py       ranked table + JSON writer + book-mismatch warning
config.py              book, tournaments, weights, staleness, odds range, toggles
fixtures/              real pulls = regression anchors (drop sample.json here)
data/                  workflow output lands here
.github/workflows/     probe-odds.yml (coverage gate) + fetch-odds.yml (pull)
CLAUDE.md              operating brief for Claude Code
DATA_CONTRACT.md       reverse-engineered API shape + what we know / don't know
SESSION1_PROMPT.md     paste this into Claude Code to start
```

## What's provisional (finalize once real Betwinner data lands)
- **Composite weights** (`config.WEIGHTS`) are a starting guess. The limit component
  auto-disables if Betwinner returns no `limit` (22bet returned null). Tune after
  seeing the real fixture.
- **De-vig method** for the margin score is proportional (per-market hold). Per-
  selection vig asymmetry (favourite-longshot) needs a different method — a
  refinement for once data confirms it's worth it. See DATA_CONTRACT.md.

Pure Python standard library. No pip install required.
