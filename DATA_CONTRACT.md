# DATA_CONTRACT.md — OddsPapi v4

Reverse-engineered from real pulls (Pinnacle + 22bet), then corrected against the
live coverage probe of 2026-07-25.

> **Coverage gate: FAILED.** Betwinner is not served on this key — requesting it
> returns 22bet's feed. Nothing below has been observed on actual Betwinner data.
> See **PROBE_FINDINGS.md** for the evidence and the open vendor questions.

## Endpoint & auth
- Host: `https://api.oddspapi.io`
- Auth: API key as a **query parameter** `?apiKey=...` (no header).
- Leagues: `GET /v4/tournaments?sportId=10&apiKey=...`   (sportId 10 = football)
- Odds:   `GET /v4/odds-by-tournaments?bookmaker={slug}&tournamentIds={csv}&apiKey=...`
- `bookmaker` is **required and single**. Three distinct responses, confirmed live
  on 2026-07-25 (see PROBE_FINDINGS.md):
  - **unknown slug** → `INVALID_PARAMETER`, and the error body helpfully lists all
    461 valid bookmakers.
  - **valid slug, no coverage for these tournaments** → `404 FIXTURE_NOT_FOUND`
    (`pinnacle` and `bet365` on tournament 34480).
  - **valid slug with coverage** → `200` + odds keyed by the book's slug.
- ⚠️ **`betwinner` is the exception and it is a trap.** It validates as a real slug
  and returns `200`, but the payload is keyed `22bet` and every `fixturePath` points
  at **22bet.com** (48/48 fixtures). Requesting `1xbet` returns 1xbet.com paths, so
  the API does label books correctly in general — betwinner specifically delivers
  another book's feed.
- The earlier claim here that "the API does not silently fall back — a book you see
  without requesting it is a stale browser tab" was **wrong**. The probe ran
  server-side on a GitHub Actions runner with no browser in the loop. The
  design-phase confusion was never a caching problem.

## Response shape
Top level: array of fixtures.
```
fixture.fixtureId, participant1Id, participant2Id, sportId, tournamentId,
        startTime (UTC), updatedAt, hasOdds
fixture.bookmakerOdds.{slug}
        .bookmakerFixtureId     # aggregator-level id — IDENTICAL across books
        .fixturePath            # deep link, e.g. https://22bet.com/line/353890790
                                #   ← the domain here is the only reliable per-book
                                #     identity signal; the {slug} key can lie
        .bookmakerIsActive, .suspended
        .markets.{marketId}
        .bookmakerMarketId      # INTEGER, opaque. NOT a market-type string. See below.
        .marketActive           # bool
        .outcomes.{outcomeId}.players.0
              .price             # DECIMAL odds  ← use this
              .priceAmerican, .priceFractional
              .active            # bool
              .bookmakerOutcomeId# INTEGER-as-string, opaque. NOT a readable label.
              .mainLine          # bool — main line vs alternative (RELIABLE)
              .limit             # max stake (present for Pinnacle; NULL for 22bet)
              .changedAt         # ISO ts ← staleness source
              .bookmakerChangedAt, .playerName, .betslip, .exchangeMeta
```

## Market type — UNRESOLVED, and `engine/parser.py` is built on the wrong shape
This section previously described `bookmakerMarketId` as a string encoding the market
type (`line/moneyline`, `altLine/totals`) and `bookmakerOutcomeId` as a readable label
(`home`, `-1.0/home`, `2.75/over`). **The real payload has neither.** Measured across
the full tournament-34480 pull:
```
bookmakerMarketId  : 30 distinct values — 17, 2854, 99, 2, 27, 15, 62 …  all INTEGERS
bookmakerOutcomeId : 73 distinct values — '10', '9', '3830', '7', '425' … all INTEGERS
```
No value contains a letter or a `/`. Consequences, measured by running the current
parser over that pull:
- `_market_type()` returns `"other"` for **7233/7233** selections.
- `_is_alt()` returns False for all of them, so **SUPPRESS rule 2 (drop alt lines when
  a main line exists) is not enforced** and `config.INCLUDE_ALT_LINES` is dead code.
- The report's `market_type` column would read `other` on every row.

What *is* usable: **`mainLine`** is a real boolean and well populated (672 True /
6561 False in that pull). Main-vs-alternative should key off `mainLine`, not off a
string prefix that does not exist.

**Resolved by reading Betwinner directly.** The numeric ids are the 1xBet platform's own
group/type codes, and betwinner.com publishes them in a form that can be decoded:
`GE[].G` is the market group and `E[][].T` the outcome type — the same numbers OddsPapi
emits as `bookmakerMarketId` / `bookmakerOutcomeId`. `G=1, T=1/2/3` is 1X2
home/draw/away, matching OddsPapi's `bookmakerMarketId=1` exactly. The mapping now lives
in `engine/bwfeed.py` (`GROUP_TYPES`, `OUTCOME_LABELS`), covering the groups established
from real payloads; anything unconfirmed stays `other` rather than being guessed.

Main-vs-alternative is likewise solved: the feed sets `CE = 1` on the book's own main
line for each group. Checked against OddsPapi's `mainLine` labels for the same fixture,
it agrees to the decimal on the team-total groups.

Scanning Betwinner's own feed (`engine/bwfeed.py`) therefore enforces SUPPRESS rule 2
properly. The OddsPapi path still cannot — that limitation is specific to reading
Betwinner's prices through OddsPapi's `22bet` key.

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
- **`limit`**: Pinnacle yes, 22bet null. Betwinner **still UNKNOWN** — the 2026-07-25
  probe never reached Betwinner, so it could not answer this. The 22bet pull it did
  return was null on 7233/7233 selections, consistent with what was already recorded
  for 22bet. If null, the limit score disables. Higher limit did NOT predict better
  pricing in the 22bet sample, so don't overweight it even if present.
- **Rate limit**: `/v4/odds-by-tournaments` rejects back-to-back requests with
  `RATE_LIMITED` and a "wait ~0.7 s" message. The exact policy is undocumented. A
  probe loop without spacing reads this as a plain non-200, which looks identical to
  "no coverage" — a silent false negative. `probe-odds.yml` now spaces requests and
  retries on `RATE_LIMITED`.
- **Off-season = mostly closed.** In EPL (id 17) ~94% of 22bet markets were inactive
  (fixtures a month out). Target tournaments with `upcomingFixtures`/`liveFixtures` > 0
  (34480 Conference, 390 Brazil B, 325 Brazil A). PL 17 is off-season.
- **Staleness:** trust `changedAt`; old timestamps appear even inside "active" markets.
  The scanner measures staleness relative to the freshest line in the pull, so a saved
  fixture still filters sensibly regardless of when `scan.py` is run.

## Reference data point (from the 22bet sample, for schema sanity only)
Pinnacle mean overround ≈ 6.3%. This is NOT Betwinner's margin — Betwinner's hold is
unknown until pulled. Do not assume Betwinner ≈ 22bet; measure it.
