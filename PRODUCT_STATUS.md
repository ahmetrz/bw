# PRODUCT_STATUS.md — the scanner as a prediction product

Written 2026-07-25, at the operator's request, from three seats: system architect,
betting-market PM, and the bettors who would use it. Everything below is grounded in
what was actually built and measured this session — no aspirational claims.

## What the product is today, in one paragraph

A pipeline that reads Betwinner's own pre-match feed (no key), normalizes every market,
ranks selections by within-book cheapness (per-type margin normalization), expresses a
directional view in its safest market form above 1.10 (laddering; outright win banned in
football), assembles a one-per-match parlay with honest hard-rule-4 math, and renders a
phone-friendly slip of deep links. One external model exists (ClubElo football) and is
deliberately not wired into ranking because nothing is backtested. Seven sports have
verified data-source references; four rules references are being researched now.

## Architect's view

**Sound.** Feed decoded (CMG/PN sub-game semantics, CE=1 main-line marker, numeric
group ids for 9 market families); dedup on real match id; placeholder suppression;
per-type margin normalization; regression suite (11 tests) pinning every bug found;
checkpointed, budget-bounded sweeps after the first one ran 3.5h and risked total loss.

**Fragile, in order of severity.**
1. **No feedback loop.** We never ingest settled results. Without results there is no
   backtest, no calibration, no error measurement — the product cannot learn or even
   know when it is wrong. This is the single biggest architectural hole.
2. **Model coverage.** ClubElo reached 2 of 22 sample fixtures. Everything outside
   ~60 European football leagues has no model, hence no direction, hence no ladder pick.
3. **Market-id mapping is partial.** 9 group families decoded; a large "other" mass
   (4,360 of 11,344 rows in one pull) is unlabelled, so type-normalization and ladders
   cannot reach it.
4. **Undocumented feeds everywhere.** Betwinner LineFeed, Setka API, Bo3.gg, ESPN —
   none contractual, all can change or vanish silently. Fixture-pin everything.
5. **No time series.** Every pull is one snapshot; line movement, steam, and closing
   lines are invisible. Scheduling needs operator approval (quota/HITL 5).
6. **Datacenter-IP wall.** NBA.com, KHL, FanGraphs, PFR, Sofascore all block the IPs
   GitHub Actions runs from. Architecture must route around them (verified
   alternatives are recorded per sport in research/).

## PM's view (betting-market seat)

**Honest positioning.** This is a *market-structure scanner and slip-construction tool*,
not a prediction engine yet. It finds where Betwinner prices a family of markets
cheaply and expresses views in maximum-safety form. The parlay math is deliberately
anti-marketing: 50 legs at the measured 7.14% median hold returns 0.032 of stake in
expectation and the product says so on the slip itself.

**What would make it a prediction product.** A results loop and calibration. Until
model probabilities are scored against outcomes (Brier/log-loss per sport/league/market,
calibration curves), "edge" is a research column, and the weights must keep ignoring it.

**Risk register, plainly.**
- *Data licences:* Sackmann and TML are non-commercial; MoneyPuck needs written
  permission for commercial use; ESPN's robots.txt names anthropic-ai (Disallow: /) and
  Natural Stat Trick names the Claude bots explicitly. Respected in code and docs; any
  commercialization forces a licensing pass.
- *Book ToS:* automated access to Betwinner's feed and any future automated slip-filling
  sit under the book's terms; accounts get limited or closed for less. The coupon page
  deliberately stays on the manual side of that line.
- *Jurisdiction:* offshore books occupy a legally grey-to-prohibited position in several
  jurisdictions, including the operator's. Product decisions, not engineering ones —
  recorded, not resolved.
- *Key-man feeds:* Liga Pro / TT Elite have no first-party source at all; Flashscore's
  archive stops 2024-06. The second-biggest sport by volume rests on one open API
  (Setka) plus aggregators.

**Priorities (PM ordering, with reasons).**
- **P0 — results ingestion + backtest harness.** Everything else compounds on it.
  Sources already verified: fdcouk, openfootball, FIVB VIS, Setka API, NHL API, bo3.gg.
- **P0 — finish the 48h sweep reliably** (budget/checkpoint version now running) and
  complete the market-id map from its payloads.
- **P1 — table-tennis points-Elo.** Second-biggest volume, best API, weakest bookmaker
  attention — the most plausible place for genuine residual edge (session fatigue,
  stale ratings on circuit entrants).
- **P1 — ladder wiring for tennis / basketball / hockey** from real 48h payloads, plus
  rules-aware settlement labels (the four rules agents' output).
- **P2 — line-movement snapshots** (needs operator cadence approval), lineup/injury
  feeds close to kickoff, a Poisson fallback model from fdcouk for football outside
  ClubElo's coverage.

## Bettors' view — four profiles

**1. The accumulator player (the operator's own profile).** Wants a 50-leg safest-form
slip above 1.10 per leg, on the phone, fast. *Served today:* ladder + one-per-match
parlay + mobile slip with deep links and honest math. *Missing:* ladders beyond
football; a "starts in the next N hours" filter; automatic re-pricing when a line
moves between generation and tapping; slip import (blocked by the book's auth wall —
by design).

**2. The value seeker.** Wants +EV singles against a calibrated model, stake sizing,
CLV tracking. *Served today:* an uncalibrated edge column on ~2 fixtures. *Missing:*
everything that makes edge trustworthy — results, calibration, closing-line capture.
This user should not trust the product yet, and the product says so.

**3. The casual evening bettor.** Wants tonight's card, simple, mobile. *Served
today:* the slip page renders fine on a phone and remembers progress. *Missing:*
time-window and league filters, per-sport tabs, Turkish-language labels.

**4. The sharp.** Wants limits, line history, closing line value, market depth.
*Cannot be served:* Betwinner publishes no limits in this feed, we have no line
history yet, and a free public model does not out-price a book's traders. The honest
answer to this profile is "wrong tool" — and the docs already say a positive computed
edge is more likely model error than mispricing.

## Missing data, consolidated (the operator's question, answered flat)

1. Settled results per sport (the feedback loop) — verified free sources exist.
2. Closing-line snapshots of Betwinner itself (needs scheduled pulls — approval gate).
3. Full numeric market-id → type map (the "other" mass).
4. Lineups/injuries near kickoff (football XI, NBA injury PDF, NHL goalie confirms;
   European hockey goalies UNSOLVED — revisit September).
5. Referee assignments (football cards; NBA crews).
6. Venue coordinates for weather joins (Wikidata SPARQL, ready to wire).
7. Betwinner's own settlement terms (payout cap, max legs, dead-heat/retirement rules)
   — generic conventions are being researched; the book's specifics need reading.
8. Historical odds/limits from the book itself — do not exist publicly; only our own
   accumulating snapshots can build this.

## Analyses not yet done, consolidated

1. Backtest + calibration per sport/league/market (blocked on results loop).
2. CLV study (blocked on snapshot cadence).
3. Hold-structure atlas per sport and league (football done; others once 48h lands).
4. Name-matching QA at scale (ClubElo join rate; team-name normalization).
5. Parlay correlation analysis (same-league, same-day legs are not independent even
   across matches — weather, referee pools, league scoring waves).
6. Table-tennis session-fatigue effect size (data ready in Setka API).
7. Model-vs-book disagreement audit: when edge > x, who was right, by segment.
