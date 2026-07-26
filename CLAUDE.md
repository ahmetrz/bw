# CLAUDE.md — Betwinner Odds Scanner

## What this project is
A **single-book scanner** for Betwinner. Pull every open market across the configured
tournaments, score each selection by a combination of criteria, rank, return the top
50. There is **no reference book** and the tool makes **no value/"beat the sharp"
claim** — it ranks selections within Betwinner's own prices. It emits a report; it
does not place bets.

## Trigger → Transformation → Output
- **Trigger:** the DAILY run (`.github/workflows/daily.yml`, cron 06:10 UTC, operator-
  approved cadence: once a day) fetches the next 48 hours of Betwinner's pre-match card
  via GitHub Actions; the operator's machine blocks the site. Manual dispatch also works.
- **Transformation:** normalize → drop outrights and multi-day sports → model assigns a
  DIRECTION → ladder converts it to its safest form → odds gate at 1.10 → confidence
  floor → one selection per match. The composite score still ranks by within-book
  cheapness for the scan path.
- **Output:** `daily_report.json` + `picks.html` — a self-contained, filterable page of the
  numbered selections, sent to Telegram as an attachment with a SHORT notice as its
  caption. The message used to carry all fifty-odd selections across nine chunks, which
  could not be sorted, filtered or searched; the list now lives on the page and Telegram
  only says it exists. The scan path separately writes `report.json` and, on demand,
  `coupon.html` — that one ranks by within-book cheapness, NOT by the model, so it is
  deliberately not produced by the daily run.

## The daily rule, in order (this is the product)
1. **The model picks the direction.** Never the price. A short price is a probability
   estimate plus the book's margin plus its exposure; reading it as a probability hands
   the book's own opinion straight back to it.
2. **The ladder picks the form** — the safest expression of that same view.
3. **Odds are read at exactly one point:** the `MIN_ODDS` (1.10) gate. Nowhere else.
4. **A confidence floor** (`MIN_MODEL_SURVIVAL`) throws away anything the model is not
   actually sure of. Without it the ladder returns the safest form of a coin flip, which
   is still a coin flip.
5. **Refund (push) markets are OFF** (`ALLOW_PUSH_MARKETS = False`). Whole-number
   handicaps, quarter handicaps and whole-number totals can all return the stake instead
   of winning, so they are excluded and only half-lines survive. With them gone the
   confidence floor is a floor on WINNING rather than on merely surviving. The ladder
   still walks down to the next clean rung rather than dropping the match — on a live
   card "+0.75 handikap" became "kaybetmez", not nothing.

A match where the model has no confident view yields NOTHING. Padding the slip with the
least-bad option available would defeat the whole exercise.

## Architecture (Parser → Rule Engine → Reporting)
```
scan.py                entrypoint for the ranked scan
tools/daily_report.py  the daily run: windows → picks → score → page → Telegram
tools/fetch_window.py  sports → tournaments → fixtures → markets, budgeted+checkpointed
tools/make_picks_page.py  picks.html: the numbered, filterable, sortable day's list
tools/make_coupon.py   scan-path slip of deep links (NOT the daily product)
engine/bwfeed.py       Betwinner feed → normalized rows (market keying, coverage)
engine/parser.py       OddsPapi response → the same rows (book-agnostic)
engine/score.py        hard filters + composite score
engine/ladder.py       safety laddering; three-way vs two-way read off the payload
engine/pick.py         direction + ladder + gates → one selection per match
engine/rating.py       the 0-100 score: 70 model confidence + 30 evidence, no price
engine/model_football.py  ClubElo: 1X2, totals AND the goal-difference distribution
engine/settlement.py   what a selection actually means when it settles
engine/telegram.py     daily notification (no-ops without credentials)
engine/tr.py           Turkish labels for everything user-facing
config.py              gates, weights, exclusions, windows
research/              per-sport statistics, free sources, rules traps (64 sports)
fixtures/              real pulls = regression anchors
```

## Secrets
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub Actions secrets. Their absence is
NOT an error: the run still scans, still writes the report, and reports the send as
skipped. A credential problem must never fail a scan that otherwise worked.

## The composite score (per selection, each component 0–1, weighted)
1. **margin_score** — from the selection's MARKET overround (lower hold → higher
   score), normalized **within the selection's market type** (`MARGIN_NORM_PER_TYPE`).
   NOTE: under proportional de-vig every selection in a market shares the same
   self-edge, so this is effectively a per-*market* quantity. Per-selection vig
   asymmetry needs a non-proportional method (Shin / additive) — a later refinement,
   not assumed here.
   Normalizing across the whole run was tried first and made the ranking a market-type
   sort: on real Betwinner data totals started at 6.38% hold while no moneyline market
   priced below 7.27%, so the top 50 came back 100% totals under every weighting,
   including margin 1.0 / range 0.0. A totals hold and a 1X2 hold measure different
   products; the answerable question within one book is how cheap a market is for its
   own kind. Types with fewer than `MIN_MARKETS_PER_TYPE` markets fall back to the
   global scale, otherwise a sparse type would normalize flat and score every one of
   its selections 1.0. Scaling also uses a percentile ceiling over DISTINCT markets —
   raw min/max over rows let 100%+ hold exotics flatten every real score to 1.000.
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
6. **Direction never comes from the price.** See "The daily rule" above. This is the one
   invariant most likely to be violated by accident, because sorting by short prices
   looks like sorting by safety and is not. The **0-100 score obeys the same rule**:
   `engine/rating.py` reads model survival and evidence quality only, and a test asserts
   the score does not move when the odds change. A score that quietly folded the price
   back in would rank by the book's opinion while looking like analysis — and it would go
   unnoticed for weeks, because a short price and a confident model agree often enough.
   The score is 70 points of confidence measured **from the floor upward** (a selection
   that only scrapes past `MIN_MODEL_SURVIVAL` scores near 0, not near 75, since passing
   the floor is the entry condition rather than an achievement) plus 30 points of
   evidence (name-match strength, matches behind the division, sample behind the rating
   bucket). Selections are numbered 1..N by score, once across the whole card, so a bet
   keeps the same number in both windows.
7. **Only emit what settles the same day.** Outrights are dropped structurally (an entry
   with no second participant is not a head-to-head, which also removes tournament
   winners, election questions, novelty bundles and multi-runner races in one rule), and
   sports whose head-to-heads span days sit in `config.MULTI_DAY_SPORTS`. Do NOT filter
   on the start timestamp for this: long-dated markets carry a near-term start. The 2026
   Senate markets are stamped 5–16 days out because that is when the LINE runs.
8. **RNG markets never enter the ranking.** Lottery measured a 3.09% median hold against
   football's 8.65%, so left in they head every run. No model can ever justify one.
   `config.EXCLUDED_SPORTS`.
9. **Qualify a source on its BODY, never its status code.** Learned repeatedly and the
   hard way: a 200 has been a Cloudflare block page, an Incapsula interstitial, a
   proof-of-work challenge, an empty array, a "we're renovating" placeholder and a 404
   page with a 257 KB body. Read the bytes.
10. **Check robots.txt for OUR crawler by name before fetching.** ESPN disallows
    `anthropic-ai`; FIVB, Natural Stat Trick, Tapology, CueTracker and others name
    `ClaudeBot`. A source already recorded as verified can become disallowed — FIVB did.

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
