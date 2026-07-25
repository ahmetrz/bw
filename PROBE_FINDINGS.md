# PROBE_FINDINGS.md — coverage gate result, 2026-07-25

Evidence log for the CLAUDE.md coverage gate. Every line below is from a live
`probe-odds.yml` run on a clean GitHub Actions runner (no browser, no cache),
tournament **34480** (UEFA Conference League), sportId 10.

## Verdict

**Betwinner is NOT served on this key. Requesting `bookmaker=betwinner` returns
22bet's feed.** The scanner must not be pointed at this data as Betwinner
(CLAUDE.md hard rule 5). Session 1's scanner validation and weight tuning stay
blocked until the data source is resolved.

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
