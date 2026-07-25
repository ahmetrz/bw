# PROBE_FINDINGS.md — coverage gate result, 2026-07-25

Evidence log for the CLAUDE.md coverage gate. Every line below is from a live
`probe-odds.yml` run on a clean GitHub Actions runner (no browser, no cache),
tournament **34480** (UEFA Conference League), sportId 10.

## Verdict — REVISED after direct measurement against betwinner.com

Requesting `bookmaker=betwinner` returns a payload keyed `22bet`. The first reading
was that this is the wrong book. **Measurement against Betwinner's own site says
otherwise: Betwinner and 22bet publish the same prices.** See "Betwinner ≡ 22bet"
below — 119 of 132 cleanly comparable selections across 12 fixtures match to the
decimal, and the 13 that differ are all ≤1.2% apart, consistent with the ~40-minute
gap between the two pulls.

So OddsPapi is not substituting a *different* book's prices; it is serving Betwinner's
prices under the platform's canonical `22bet` key. Whether that satisfies CLAUDE.md
hard rule 5 is the operator's call — the rule is about not proceeding on another
book's data, and on this evidence the data is not another book's.

What remains true: OddsPapi never labels the payload `betwinner`, and its `fixturePath`
points at 22bet.com, so nothing in the response identifies it as Betwinner. The label
problem is real even though the price problem is not.

## What each slug returned

| Requested slug   | HTTP | Key in `bookmakerOdds` | `fixturePath` domain | Reading |
|------------------|------|------------------------|----------------------|---------|
| `betwinner`      | 200  | `22bet`                | **22bet.com**        | substituted |
| `22bet`          | 200  | `22bet`                | 22bet.com            | genuine |
| `1xbet`          | 200  | `1xbet`                | 1xbet.com            | genuine |
| `pinnacle`       | 404  | —                      | —                    | valid slug, no coverage here |
| `bet365`         | 404  | —                      | —                    | valid slug, no coverage here |
| `zzz_not_a_book` | 400  | —                      | —                    | `INVALID_PARAMETER` |

## The proof: `fixturePath`

Each fixture carries `bookmakerOdds.<book>.fixturePath`, a deep link into the
book's own site. For the same fixture (`bookmakerFixtureId` 353890790):

```
requested betwinner -> https://22bet.com/line/353890790     <-- 22bet's product
requested 22bet     -> https://22bet.com/line/353890790
requested 1xbet     -> https://1xbet.com/line/353890790
```

`fixturePath` matched 22bet on **48/48** fixtures for the betwinner request, and
matched 1xbet on **0/48**. So this is not a cosmetic labelling quirk — the payload
returned for `betwinner` points at 22bet's product pages.

`bookmakerFixtureId` is identical (353890790) across all three books, so that field
is an aggregator-level id, not a per-book one. The domain in `fixturePath` is the
per-book signal.

## Same-feed confirmation

The `betwinner` pull (18:31 UTC) and the `22bet` pull (18:38 UTC) are the same feed
seven minutes apart, not two books that happen to look alike:

- identical selection set — 7233 both sides, **0** unique to either
- of the 7024 selections whose price matched, `changedAt` matched on **7022**
- all **209** selections whose price differed had a strictly newer `changedAt` in
  the later pull

For contrast, `1xbet` pulled at the *same instant* as `22bet` differs: 7231 vs 7233
selections, and 164 price differences. Sibling books on one platform, but distinct
feeds — which is exactly why the betwinner result stands out.

## Betwinner ≡ 22bet — measured directly against betwinner.com

Betwinner's own site exposes the 1xBet-platform line feed, no API key required:

```
https://betwinner.com/service-api/LineFeed/GetGameZip?id=<gameId>&lng=en&partner=159&…
```

The earlier empty responses were caused by `partner=51`, which is **1xBet's** partner
id — it returns zero sports on betwinner.com. Betwinner's own ids (159, 169, and most
values in the 71–300 range) return the full line. Nothing was geo-blocked.

The lever that makes the comparison exact: `bookmakerFixtureId` is **identical across
all three books** (it is the platform's game id), so the same fixture can be requested
from Betwinner directly and lined up against OddsPapi's payload selection by selection,
matching OddsPapi's `bookmakerMarketId`/`bookmakerOutcomeId` to the feed's `G`/`T`.

Petrocub v Borac Banja Luka, main 1X2:

```
betwinner.com   1 = 3.23   X = 3.6   2 = 2.06   -> hold 7.28%
OddsPapi 22bet  1 = 3.23   2 = 3.6   3 = 2.06   -> hold 7.28%
```

Across 12 fixtures (OddsPapi pulled 18:38 UTC, betwinner.com ~40 min later):

| result | fixtures |
|---|---|
| every comparable selection identical | 10 of 12 |
| some drift | 2 (0/11 and 9/11) |
| **total** | **119/132 identical = 90.15%** |

All 13 differences are ≤1.2% (largest: 4.15 vs 4.20), clustered in two matches whose
lines moved during the gap. That is drift, not a different price source.

### The contrast that makes this conclusive: 1xbet is genuinely different
22bet and 1xbet pulled at the **same instant** differ on 2.27% of selections (164 of
7231) — and those differences are large: median 0.56%, p99 **18.75%**, max **44.69%**
(5.86 vs 4.05). Running the scoring engine over each and comparing the ranked output,
the **top-50 overlaps on only 37 selections and the top-10 on 7**.

So "same platform family" does not imply same prices — 1xbet proves it. Betwinner
matching 22bet to the decimal, across fixtures, with only sub-1.2% drift, is a
qualitatively different signature. Betwinner and 22bet are one price feed; 1xbet is
its own.

### Two consequences worth acting on
1. **betwinner.com's feed is a free, key-less Betwinner source** and is *richer* than
   OddsPapi's: 298 priced selections for that fixture versus OddsPapi's 147.
2. **It decodes the numeric market ids.** `G=1, T=1/2/3` is 1X2 home/draw/away — the
   same `bookmakerMarketId=1`, `bookmakerOutcomeId=1/2/3` that OddsPapi emits. The feed
   is the reference table that the market-type problem below needs.

## Two documented assumptions this disproves

1. **"The API does not silently fall back — a book you see without requesting it is
   a stale browser tab, not the API."** False. This ran server-side with no browser
   involved. The design-phase confusion was never a caching problem.

   The refined rule: for a slug with no coverage the API returns a clean 404
   (`FIXTURE_NOT_FOUND`, as `pinnacle` and `bet365` did), and for an unknown slug an
   `INVALID_PARAMETER` listing all 461 valid books. `betwinner` does neither — it is
   advertised as valid and returns 200 carrying another book's data. That is a
   vendor-side defect, not a coverage gap.

2. **The market schema in DATA_CONTRACT.md.** `bookmakerMarketId` is documented as a
   string encoding the market type (`line/moneyline`, `altLine/totals`) and
   `bookmakerOutcomeId` as a label (`home`, `2.75/over`). In the real payload both
   are plain integers — 30 distinct market ids (17, 2854, 99, 2, …) and 73 distinct
   outcome ids ('10', '9', '3830', …), with no letters or `/` anywhere.

   Consequence for `engine/parser.py`: `_market_type()` returns `"other"` for
   **7233/7233** selections and `_is_alt()` returns False for all of them, so
   **SUPPRESS rule 2 (drop alt lines when a main line exists) cannot be enforced**
   and `INCLUDE_ALT_LINES` is dead code. The `mainLine` boolean is present and
   sound (672 True / 6561 False) and is the viable substitute signal. Mapping the
   numeric market ids to market types needs a reference table we do not have.

## Field notes from this payload (22bet, tournament 34480)

Recorded for schema work only — this is **not** Betwinner data.

- 48 fixtures, 3234 markets, 7233 selections
- `limit`: **null on 7233/7233** — matches the previously recorded 22bet behaviour
- `marketActive`: True on 3234/3234; outcome `active`: False on only 47/7233
- `changedAt`: present on every selection

## Second provider: odds-api.io — key does not authenticate

Tried as an alternative source, since odds-api.io lists BetWinner among its
sportsbooks and has a free tier.

- Secret resolved: **`ODDS_API_KEY`** (32 characters). Value never logged.
- `/v3/events?apiKey=…&sport=football` → **401** `{"error":"You need to provide a
  valid apiKey"}`.
- Six request variants all returned that same 401, so the request shape is not the
  problem: `api2.odds-api.io` host, `x-api-key` header, `Authorization: Bearer`,
  `api_key=`, `key=`, and a request carrying `league`.

### `/v3/sports` and `/v3/bookmakers` are OPEN endpoints — do not use them as proof
Both return **200 for a completely fabricated API key** (tested directly). The first
version of the probe treated a 200 from `/v3/sports` as "auth verified" and reported
success; that was a **false positive**, now corrected — the auth canary is `/v3/events`,
which actually validates.

This matters beyond the probe: `"BetWinner", "active": true` in the `/v3/bookmakers`
response is the provider's **public catalogue**, not a statement about what this key
may fetch. It is the same trap as OddsPapi's "valid bookmakers" list — a name in a
listing is not coverage. Nothing about odds-api.io's Betwinner data has been verified,
because no authenticated call has succeeded.

Candidate explanations, none confirmed: the key belongs to a different vendor (32-char
hex is the house style of the-odds-api.com, a *different* company); the odds-api.io
account is not activated, or its free-plan bookmaker selection has not been made; or
the value was truncated when it was stored. The key was **not** tried against any other
vendor — sending a credential to a service it may not belong to would leak it.

## The key is a the-odds-api.com key — valid, but no Betwinner

Tested with the operator's go-ahead, since ownership was unclear. `/v4/sports` is a
sound canary there: it answers `401 INVALID_KEY` for a fabricated key.

- `GET /v4/sports?apiKey=…` → **200**. The key is valid on **the-odds-api.com**.
  `x-requests-used: 30`.
- `GET /v4/sports/soccer_argentina_primera_division/odds?apiKey=…&regions=eu&markets=h2h`
  → 200, 24 events.

Bookmakers this key actually returns (not a catalogue — the books present in the
response):

```
winamax_de 24 · winamax_fr 24 · betclic_fr 23 · onexbet 22 · codere_it 22
marathonbet 22 · unibet_fr 21 · betsson 20 · nordicbet 20 · betfair_ex_eu 19
leovegas_se 15 · unibet_se 15 · betonlineag 12 · pinnacle 11 · everygame 6
betanysports 6
```

**Betwinner: absent.** The only 1xBet-family member is `onexbet` (1xBet itself).
So this key does not solve Betwinner either.

### But it does carry Pinnacle — which changes what this project could be
`pinnacle` appears in 11 of 24 events. CLAUDE.md's whole design rests on "there is
**no reference book**", which forces the within-book-margin scoring and the explicit
refusal to make a value claim. That constraint came from having only one book. With
Pinnacle available as a sharp reference, genuine value detection — comparing a soft
book's price against a de-vigged sharp line — becomes possible for the first time.

This is a product decision, not a code change to make unilaterally. Flagged for the
operator; nothing in the scanner has been altered on the strength of it.

## Open questions for OddsPapi

1. `betwinner` is listed among the valid bookmakers but returns 22bet's feed
   (`fixturePath` → 22bet.com). Is Betwinner actually available on this plan? If
   not, why does the slug validate instead of returning `FIXTURE_NOT_FOUND`?
2. Is there a reference mapping numeric `bookmakerMarketId` / `bookmakerOutcomeId`
   values to market types and outcome labels?
3. What is the documented rate limit for `/v4/odds-by-tournaments`? Back-to-back
   requests returned `RATE_LIMITED` asking for a ~0.7 s wait.

## Reproducing

```
Actions > probe-odds > Run workflow
  tournament: 34480
  books:      betwinner,22bet,1xbet
```
Read the log: it prints the requested slug, the book actually returned, the HTTP
code and the output filename. Output files are named after the **returned** book,
so a filename never promises a book it does not carry.
