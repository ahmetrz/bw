# DATA_CONTRACT.md — OddsPapi v4

Reverse-engineered from real pulls (Pinnacle + 22bet). Betwinner uses the same
aggregator, so the same normalized schema applies — but Betwinner's coverage and its
per-field behaviour (especially `limit`) are UNCONFIRMED until the probe runs.

## Endpoint & auth
- Host: `https://api.oddspapi.io`
- Auth: API key as a **query parameter** `?apiKey=...` (no header).
- Leagues: `GET /v4/tournaments?sportId=10&apiKey=...`   (sportId 10 = football)
- Odds:   `GET /v4/odds-by-tournaments?bookmaker={slug}&tournamentIds={csv}&apiKey=...`
- `bookmaker` is **required and single**. Missing/multiple/unknown slug → `400`.
  The API does **not** silently fall back — a book you "see" without requesting it is
  a stale browser tab, not the API. (This is why every design-phase Betwinner pull was
  actually cached 22bet.)

## Response shape
Top level: array of fixtures.
```
fixture.fixtureId, participant1Id, participant2Id, sportId, tournamentId,
        startTime (UTC), updatedAt, hasOdds
fixture.bookmakerOdds.{slug}.markets.{marketId}
        .bookmakerMarketId      # string; encodes market TYPE (parse THIS, not marketId)
        .marketActive           # bool
        .outcomes.{outcomeId}.players.0
              .price             # DECIMAL odds  ← use this
              .priceAmerican, .priceFractional
              .active            # bool
              .bookmakerOutcomeId# label: "home"/"draw"/"away", "-1.0/home", "2.75/over"
              .mainLine          # bool — main line vs alternative
              .limit             # max stake (present for Pinnacle; NULL for 22bet)
              .changedAt         # ISO ts ← staleness source
```

## Market type — from `bookmakerMarketId`
`marketId` (numeric) is not semantic; parse the string. It contains one of
`moneyline` / `spreads` / `totals` / `teamTotal`, with prefix `line/` (main) or
`altLine/` (alternative).
- **moneyline** → 1X2. Labels `home` / `draw` / `away`.
- **spreads**   → handicap. Labels `-1.0/home`, `0.25/away`, …
- **totals**    → over/under. Labels `2.75/over`, `3.0/under`, …
- **teamTotal** → per-team O/U. Labels `home/1.5/over`, `away/0.5/under`, …
- `mainLine=true` = primary line; else alternative.

## What we compute in single-book mode
Within-book margin only (no external reference):
```
implied_i = 1 / decimal_odds_i
overround = Σ_i implied_i − 1        # per market; only if ≥2 outcomes and Σ>1 (the hold)
fair_i    = implied_i / (1 + overround)   # proportional de-vig
```
Under proportional de-vig, self-edge `= odds_i·fair_i − 1 = −overround/(1+overround)`
is identical for every selection in a market. So the margin signal is per-MARKET
(the hold), not per-selection. To rank selections *within* a market by vig you need a
non-proportional method:
- additive/equal-margin: `fair_i = implied_i − overround/n` → self-edge scales with odds
  (longshots penalised more).
- Shin / power methods: model favourite-longshot bias.
Pick one **after** real Betwinner data confirms the asymmetry is worth modelling.

## Field notes / gotchas (paid-for lessons)
- **`limit`**: Pinnacle yes, 22bet null. Betwinner UNKNOWN — the probe reports it.
  If null, the limit score disables. Higher limit did NOT predict better pricing in
  the 22bet sample, so don't overweight it even if present.
- **Off-season = mostly closed.** In EPL (id 17) ~94% of 22bet markets were inactive
  (fixtures a month out). Target tournaments with `upcomingFixtures`/`liveFixtures` > 0
  (34480 Conference, 390 Brazil B, 325 Brazil A). PL 17 is off-season.
- **Staleness:** trust `changedAt`; old timestamps appear even inside "active" markets.
  The scanner measures staleness relative to the freshest line in the pull, so a saved
  fixture still filters sensibly regardless of when `scan.py` is run.

## Reference data point (from the 22bet sample, for schema sanity only)
Pinnacle mean overround ≈ 6.3%. This is NOT Betwinner's margin — Betwinner's hold is
unknown until pulled. Do not assume Betwinner ≈ 22bet; measure it.
