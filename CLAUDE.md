# CLAUDE.md — Betwinner Odds Scanner

## What this project is
A **single-book scanner** for Betwinner. Pull every open market across the configured
tournaments, score each selection by a combination of criteria, rank, return the top
50. There is **no reference book** and the tool makes **no value/"beat the sharp"
claim** — it ranks selections within Betwinner's own prices. It emits a report; it
does not place bets.

## Trigger → Transformation → Output
- **Trigger:** manual dispatch or cron → fetch Betwinner odds for the configured
  tournaments (via GitHub Actions; the operator's machine blocks the site).
- **Transformation:** normalize → hard-filter (open, not stale, main line unless
  alt-scan) → composite score (margin + limit + range) → rank → top N.
- **Output:** ranked SINGLES as `report.json` + a human-readable table.

## Architecture (Parser → Rule Engine → Reporting)
Same three-layer shape as the ITSM classifier / Inspection Engine.
```
scan.py            entrypoint
engine/parser.py   response → normalized rows (book-agnostic: works for any slug)
engine/score.py    hard filters + composite score + tiering
engine/report.py   ranked table + JSON + book-mismatch warning banner
config.py          book, tournaments, weights, staleness, odds range, toggles
fixtures/          real pulls = regression anchors
```

## The composite score (per selection, each component 0–1, weighted)
1. **margin_score** — from the selection's MARKET overround (lower hold → higher
   score), normalized across the run. NOTE: under proportional de-vig every selection
   in a market shares the same self-edge, so this is effectively a per-*market*
   quantity. Per-selection vig asymmetry needs a non-proportional method (Shin /
   additive) — a later refinement, not assumed here.
2. **limit_score** — normalized `limit` (higher → more liquid/confident). If Betwinner
   returns no limit (22bet returned null), this component **auto-disables** and its
   weight redistributes to the others. Do not fabricate a limit.
3. **range_score** — plateau over the configured odds band (`config.ODDS_RANGE`),
   decaying outside it.

`score = Σ wᵢ · componentᵢ`. Weights in `config.WEIGHTS` are provisional; tune against
the first real Betwinner fixture.

## Hard rules (engineering invariants — do not violate)
1. **Every emitted selection carries:** odds, implied_prob, market_overround,
   margin_score, limit_score, range_score, total_score, limit, staleness_seconds,
   market_type, main_line, flags. A row missing any of these is a bug.
2. **SUPPRESS (never emit):** market or outcome inactive; `changedAt` older than the
   staleness window; alt-lines when a main line exists, unless an explicit alt scan.
3. **Default deliverable is the top-N SINGLES table.** Do not emit a parlay by default.
4. **Parlay is opt-in (`--parlay`).** Because there is no reference, a parlay can only
   be described in the book's OWN implied numbers. When requested, output MUST show:
   combined decimal odds, combined book-implied probability (Π of book-fair probs),
   the book expected-return multiple (Π 1/(1+hold_leg), which is < 1 and worsens per
   leg), and the payout-cap caveat. Never present this as positive value — by
   construction within one book it cannot be.
5. **Never fabricate odds or limits.** If the loaded data's book ≠ the requested book,
   or the API 4xx's, STOP and report — never proceed on fallback data.

## Coverage gate — do this FIRST
Betwinner presence on the operator's key is UNCONFIRMED. Before building or trusting
anything: run `probe-odds.yml` on a live tournament and confirm the raw response
literally contains `betwinner`. If it 400s or returns another book, STOP and hand back
— the book is not on this plan and the data-source question must be solved before any
scanning is meaningful.

## Human-in-the-loop intervention points
1. **Probe result** — is Betwinner actually returned? Confirm before proceeding.
2. **Limit availability** — does Betwinner return `limit`? Determines whether the
   limit component is live; report it and adjust weights with the operator.
3. **Weight setting** — operator confirms `config.WEIGHTS`; do not silently guess.
4. **First real run sanity** — eyeball the top 50; if everything is one market type or
   one match, the filters are wrong.
5. **Before wiring scheduling/alerts that consume API quota** — operator approves cadence.

## Definition of done — Session 1
- Run the probe; record whether Betwinner is covered and whether it returns `limit`.
- Drop the first clean pull as `fixtures/sample.json`.
- `python scan.py --input fixtures/sample.json` prints a ranked top-50 table
  [match, market, selection, odds, overround, limit, staleness, score] and writes
  `report.json`, with SUPPRESS rules applied and a warning if the book is not Betwinner.
- A regression test re-runs the fixture and asserts the table is unchanged.
- Tune weights against the real data with the operator; note the limit-availability outcome.
