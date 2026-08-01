# CLAUDE.md — Betwinner Odds Scanner

## What this project is
A **single-book scanner** for Betwinner. Pull every open market across the configured
tournaments, score each selection by a combination of criteria, rank, return the top
50. There is **no reference book** and the tool makes **no value/"beat the sharp"
claim** — it ranks selections within Betwinner's own prices. It emits a report; it
does not place bets.

## Trigger → Transformation → Output
- **Trigger:** the DAILY run (`.github/workflows/daily.yml`, 06:43 UTC with 07:43/08:43
  backstops, operator-approved cadence: once a day) fetches the next **24 hours** of
  Betwinner's pre-match card via GitHub Actions; the operator's machine blocks the site.
  The backstops check the prediction log FIRST and exit before rewriting anything — a
  later run that rebuilt the page would hand over a different list from the one that was
  announced, with fresh prices and a new slip code. The 48-hour window is gone: a
  selection 40 hours out is not today's bet, its price will move, and it reappears on
  tomorrow's card anyway. Manual dispatch also works.
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
- **Result loop:** `.github/workflows/results.yml` runs **hourly** (:30). It grades what
  has finished, rebuilds the SAME page as `results.html` with each selection marked
  KAZANDI / KAYBETTİ / İADE, rebuilds `stats.html`, and refreshes the bet-slip code. Hourly
  because a bet's outcome is known when it ends and the sources now say so within the hour
  — the live watcher records a match as it finishes, flashscore carries ~570 football
  results through the day, tennisexplorer publishes the same day's sets. It notifies only
  when that day's settled count GREW, so hourly running is not hourly notifying.
- **The record across days:** `stats.html` (`tools/make_stats_page.py`), rebuilt every hour
  from `data/predictions.jsonl` alone so it cannot drift from the log. One day is 20-odd
  bets and its hit rate swings twenty points on noise; the cumulative number is the only
  one with authority and it lived nowhere but in a terminal. It carries the headline, the
  CALIBRATION table — the only one that can say the model is WRONG rather than unlucky —
  break-even against realised, and breakdowns by day, sport, market and odds band.
- **Adding to the slip:** `service-api/LiveBet/Open` takes a set of events and returns a
  five-character code; typing it into the book's "load bet slip" box drops the whole plan
  in at once. `engine/coupon.py` builds it and READS IT BACK before handing it over,
  because a slip that loads the wrong bet in one tap is worse than no slip. Four bugs got
  that far: sending `CI` (the constant id) where the slip wants `I` (the game id); sending
  a home-normalized `-1.5` that priced the OPPOSITE handicap at 9.00 instead of 1.197;
  saving under `partner=159`, which scopes the code so tightly that every other client
  answers **"Yanlış kod"** (`partner=1` is the only value readable by ~20 partner ids
  including 159); and claiming a bet type the payload cannot carry — see below.
- **What the book will not combine** (measured against it, not assumed — the slip loads as
  an ACCUMULATOR, so a barred leg makes the whole thing unplaceable and the book says so
  with no error at all):
  * **Fifty events, hard.** Past that, SaveCoupon answers *"The number of events on the bet
    slip must not exceed 50"* and refuses the WHOLE slip rather than trimming it, so the
    trim has to happen before the call. `coupon.MAX_EVENTS`, and `stake.DAILY_CAP_UNITS`
    is set to the same number so the day's plan and the day's slip hold the same bets.
  * **One selection per event.** Two outcomes on one `GameId` — two lines of a market, or
    its two sides — come back as ONE leg with `HasRemoveEvents` set. The book does not
    refuse, it silently keeps the first and drops the rest, which is how a slip claims
    fifty and delivers forty-nine. `engine/pick.py` already emits one pick per match, so
    the dedup in `coupon.create` should never fire; it is there because the failure is
    silent.
  * **`IsBannedExpress`** — the book's own per-leg flag for "may not be in an accumulator".
    **`IsRelation`** — dependent events (an outright beside a match in the same
    competition; hard rule 7 already drops outrights). **`Block`** — suspended. None of the
    three appear on the pre-match card; they exist only in the coupon read-back, which is
    where `coupon.BANNED_FLAGS` reads them. On a real 50-leg card all 48 surviving legs
    were clean on all three.
  * **A started fixture is dropped and the slip REBUILT**, not filtered — which is why a
    code cannot be minted once with the morning list. `tools/refresh_coupon.py` rebuilds it
    hourly from fixtures that have not started. Codes also expire outright: every one
    minted three days ago now answers "Incorrect code".
  * **The bet type cannot be set at all.** `Vid` looked like a clean enum — on three legs
    whose product was 1.4705, `Vid=1` returned exactly that, `Vid=3` returned 1.414, and
    `Vid=2` returned 0, which is what a set of singles has. It is not: pushed to forty legs
    the service names them itself, `Vid=2` and `Vid=4` answering *"Invalid number of events
    in System bet"* while every other value is stored as 1. So `Vid=2` is a SYSTEM bet whose
    combination was invalid and the slips shipped as "20 tekli bahis" were systems. Singles
    is a MODE in the book's own slip screen, chosen after the code loads, so the page and
    the notice say **"KOMBİNE gelir — kupon ekranından TEKLİ'ye çevir"** instead of
    claiming otherwise. One control, once.
  * Not readable to us: the book's written rules. `/en/rules` and every guessed path 404s,
    the sitemap carries no rules entry, the site footer links only to bonus rules, and the
    full rulebook lives on `betwinner2.com`, whose robots.txt is `Disallow: /`. Everything
    above therefore comes from the API's own behaviour, which is the stronger evidence
    anyway — it is what the slip will actually do.
- **How much to bet:** flat. Every selection in the plan gets the SAME stake, and the only
  lever is the daily cap on how many there are (`engine/stake.py`). Kelly and every other
  proportional rule sizes by EDGE — how far the price is from the truth — and this product
  does not claim one; feeding the model's probability in anyway would convert "the model
  is 86% sure" into "the model is 86% sure AND the book is wrong about it" and then size
  the bets on a claim it never made out loud. The reported headline is the BREAK-EVEN hit
  rate, which is arithmetic on the book's own prices and asserts nothing, and it sits
  beside the REALISED hit rate — never beside the model's confidence, which is the thing
  under test. Hit rate counts every graded selection, because a pick under the cap is
  still evidence about the model; the money counts only what was staked. On a real card:
  20 bets at 0.5% of bankroll each is 10% staked to make 2%, break-even at 83.2%, and one
  point of hit rate is worth 0.12% of bankroll — a short-odds list lives within a few
  points of its own break-even, which is the number that decides the day.

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
tools/make_picks_page.py  ONE template for picks.html and results.html
tools/daily_results.py    settles a logged day, rebuilds the page as a scorecard
tools/make_coupon.py   scan-path slip of deep links (NOT the daily product)
tools/collect_results.py  one small adapter per source -> the results store
tools/collect_live.py  watches the book's OWN live feed; every sport, every circuit
tools/build_generic_model.py  fits + calibrates any sport; refuses the ones that fail
tools/make_method_page.py  method.html, generated from signals/pick/ladder/config/research
engine/bwfeed.py       Betwinner feed → normalized rows (market keying, coverage)
engine/parser.py       OddsPapi response → the same rows (book-agnostic)
engine/score.py        hard filters + composite score
engine/ladder.py       safety laddering; three-way vs two-way read off the payload
engine/pick.py         direction + ladder + gates → one selection per match
engine/rating.py       the 0-100 score = model probability, discounted by evidence
engine/results_store.py   ONE results table per sport: date, teams, score. Nothing else.
engine/model_generic.py   ONE model for every sport, counted from that table
engine/model_football.py  ClubElo: 1X2, totals AND the goal-difference distribution
engine/settlement.py   what a selection actually means when it settles
engine/stake.py        flat stake + daily cap; a risk rule, deliberately not an edge rule
engine/coupon.py       the day's plan as ONE bet-slip code, verified before it is handed over
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

## Adding a sport (this is the whole procedure now)
1. **Add a finish condition to `SPORTS` in `tools/collect_live.py`** — one line saying
   what the score counts and what finishing looks like (a race to N sets/frames/maps, or
   N scheduled periods). The watcher then collects that sport from the book's OWN live
   feed: no source hunt, no robots question, no adapter, every circuit the book carries.
   Write an adapter only when an ARCHIVE exists and history-now beats history-later — the
   watcher starts from zero and fills at the rate the sport is actually played.
1b. If you do write an adapter in `tools/collect_results.py`, it yields `{date, home, away,
   home_score, away_score, unit}`. `unit` is what the score COUNTS — goals, points, runs,
   sets, frames or maps — and it decides which market groups the model is allowed to
   answer. Get it
   wrong and the model prices a points market off a distribution of sets: "total 76.5
   under" came back at 100.00% on a 1.79 shot, because every set total ever recorded is
   between 3 and 5. Check robots.txt for OUR crawler by name FIRST and record
   the check next to the adapter. Supply `pool` when the sport's competitions do NOT play
   each other (football divisions), and a stable `home_id`/`away_id` when the source has
   one (a name does not survive a sponsor rename; an id does).
2. `python tools/build_generic_model.py --sport <id>`.
3. Read the held-out calibration. If it holds, the sport is admitted automatically. If it
   does not, it is REFUSED and the daily run says why, every day, in the coverage report.

## Where results come from (the live watcher is the default now)
Every source before it was somebody else's and covered exactly one slice: football-data
football, EuroLeague basketball, MLB baseball, Setka **only Setka Cup** — so 58% of the
table tennis card had no source, and volleyball, snooker, darts, handball and futsal had
none at all. `LiveFeed/Get1x2_VZip` carries every sport the book runs, with both names,
both STABLE participant ids, the running score, the period breakdown and the FORMAT note.
`tools/collect_live.py` sweeps it and writes a result two ways:
  1. **The feed says so** — `SC.CPS` becomes "Match finished". Nothing is inferred.
  2. **It vanished**, and the state it was last seen in says the match was over. For a
     RACE that is the score, read against the format and never assumed: table tennis runs
     best-of-five and best-of-seven on the same day, so 3-1 is a finished match on one
     circuit and a lead on the other. For a PERIOD sport the score can never say it —
     1-0 in the second half looks exactly like 1-0 at full time — so what says it is the
     CLOCK: `SC.TS` counts up to regulation and stops, and `SC.SLS` ("84 minutes") goes
     EMPTY at the same moment. Watched to the end on three real football matches, and
     only ONE of the three ever displayed "Match finished", so rule 1 alone was dropping
     two thirds of finished football. `CLOCK_FINISH` is a list of sports whose clock has
     been WATCHED to the end, not of sports that have one: basketball and hockey are
     absent because a clock that counts down or resets each period would satisfy the rule
     at half time. Extra time is refused twice — by the period number and by the status
     wording — because its goals are not the ones our markets settle on.
It refuses a sport whose finish condition we cannot state, a tie in a sport that cannot
draw, an unreadable format, and anything gone too briefly to be sure it is gone. A watcher
that guesses is worse than no watcher: a wrong row is indistinguishable from a real one
once it is inside a rating. The one residual exposure is stated rather than hidden: a
football match that reaches 90:00 and drops off the feed for three minutes while injury
time is still being played is recorded at its 90-minute score.

**Archives are now the exception, not the plan.** Free result archives were worth hunting
while watching was rationed by a private repo's Actions quota. The repo is public, the
watcher runs fifty minutes an hour, and it collects from every sport the book carries, so
an archive is only worth writing when a sport is too THIN to accumulate — snooker at four
fixtures in 48 hours will take months to reach 400 whatever the cadence. Checked by our
crawler's name, 2026-07-26:
  * `api.snooker.org` — no robots.txt (404), but the API answers **401** without a
    registered application name. Not usable without signing up.
  * `api.openligadb.de` — no robots.txt, real JSON, 812 leagues. Its ice hockey and
    handball seasons are mostly 2008-2013, and the current ones (CHL, DEL) are not the
    competitions Betwinner's card carries. Open and useless to us, which is worth writing
    down so nobody checks it twice.
  * `dartsorakel.com` — `User-agent: *` / `Disallow:` (empty), so everything is allowed.
    HTML rather than an API; the one candidate still worth building if darts stays thin.
  * `cev.eu` — no robots.txt. A website, not a feed.
  * `volleybox.net`, `hltv.org`, `shl.se` — **403 to us on robots.txt itself**. Blocked
    before any question of permission arises.

Betwinner has a results SERVICE as well. It would replace polling with one call a day AND
backfill history, so it is worth returning to — here is exactly how far it has been taken,
so the next attempt starts from the end of this one rather than the beginning.

  * `service-api/result/web/api/v3/games` is the live route. v1, v2 and v4-v7 answer
    `UnsupportedApiVersion`; **v3 answers a clean 400**, so route and version are right.
  * **`dateFrom` and `dateTo` are real parameter names.** They are the only two that bind:
    with `dateFrom` alone the service switches from the generic `bad-request` to
    `invalidvalidationexception`, which is the model binder succeeding and validation then
    failing. Unknown names are ignored entirely (`zzzunknown=1` changes nothing), so that
    difference is the tell.
  * **They are in MILLISECONDS.** In seconds the pair is rejected; in milliseconds both
    bind. ISO strings are rejected.
  * Something REQUIRED is still missing and the `errors` object comes back empty. 42 more
    names were swept against a bound `dateFrom`/`dateTo` pair — sportId, champId, gr, ref,
    partner, country, lng, page, take, mode, platform, brandId and the rest — and not one
    changed the answer.
  * **It is not a header.** Eighteen were tried against the bound pair — Referer and Origin
    set to the site, Accept-Language, X-Requested-With, X-Auth, Authorization, X-Whence,
    X-Partner, X-Country-Id, X-Project-Id and the rest. Every one still answered
    `invalidvalidationexception`. That closes the larger of the two remaining doors.
  * **The resource decides the version, not the service.** `games` is v3, but `sports` and
    `champs` are **v2** — they answer `UnsupportedApiVersion` at v3 and the generic
    bad-request at v2. `game` (singular) exists at v1 and v2. Anyone sweeping one version
    across the whole API will read "not supported" and conclude the route is wrong.
  * **A `mobile` client path exists and is a decoy.** `result/mobile/api/v1/games` returns
    **HTTP 200**, accepts ISO and `yyyy-MM-dd` dates where the web path rejects them, and
    is the only branch that ever answers 200 at all. It is worthless: `sports`, `champs`
    and `games` under it ALL return the same `{"count":0}` — with any parameters, with
    none, for any date. A canned body, not an empty result set. Hard rule 10, arrived at
    from the other direction: the 200 here is more misleading than any of the 400s.
  So the missing field is not a header and not in that vocabulary, which leaves a body the
  route accepts despite advertising `allow: GET`, or a parameter whose name is not guessable
  — and the site's own request still cannot be read, because `/en/results/` 302s to
  `betwinner2.com` and that host's robots.txt is `Disallow: /`.
  * The app bundle does not carry the path as a string, and `/en/results/` 302s to
    `betwinner2.com`, whose robots.txt is `Disallow: /` — so the real request cannot be
    read off the site.

**Cadence is measured, and so is the yield.** A finished fixture lingers on the feed for
50-150 seconds, so the chance of catching one is roughly (linger / sweep interval): every
minute catches nearly all of them, hourly catches about 2%, which is nothing. The repo is
public so Actions minutes are unlimited, and `watch-live.yml` therefore sweeps 55 minutes
of every hour.

What that actually returns, from two complete runs rather than from an estimate: **about
43 results per run, ~1,000 a day**, of which table tennis ~490, football ~130, volleyball
~120 and esports ~60. An earlier note here said 3,600 a day; that was extrapolated from the
busiest minute of the busiest hour and was wrong by a factor of three. The daily coverage
report now computes the rate per sport from `data/watch_log.jsonl` — a ledger of what was
collected and when — and projects how many days each unmodelled sport still needs. The
store cannot answer that on its own: it keeps each fixture's own date, not the moment we
learned of it, so a watcher three hours old looks identical to one a day old.

**What the fetcher does NOT fetch is part of the design.** `tools/fetch_window.py` applies
two rules while reading the fixture list rather than after pulling a thousand markets per
fixture and discarding them. Both were already in force; only their position moved:
  * `config.EXCLUDED_SPORTS` — 750 fixtures on a live card, mostly lottery draws.
  * Hard rule 7's "no second participant is not a head-to-head" — 311 fixtures, including
    every horse and greyhound race.
Sub-games (halves, corners, "first to happen") are now opt-in via `--sub-games`. Nothing in
the daily product reads one — `engine/pick.py` drops them because full-match probabilities
do not describe a half, and `engine/edge.py` drops them again — yet they were 365,329 of
674,379 rows on a real card, 54% of the payload, fetched and normalized in order to be
skipped. The fetcher writes `<card>.skipped.json` beside the card so the daily coverage
report still names those sports and their real counts; trimming the fetch must never trim
the one report that says what was on the card and why it was left out.

There is deliberately no step for writing a model. Football, table tennis and basketball
each got a bespoke one, and both bugs that reached a live card came from that duplication
— a sign error in the basketball handicap and a table tennis logistic extrapolated past
its fitted range. `engine/model_generic.py` counts what happened instead of assuming a
distribution, so a sport with a fat draw, one that cannot draw and one scored in sets all
work with the same code. Basketball now runs on it; its bespoke model was deleted rather
than kept alongside.

`MODELLED_SPORTS` in `engine/pick.py` is the list of HAND-WRITTEN models and is meant to
SHRINK. Football left it: the hand-written Elo model is fitted on more history and reaches
18 more fixtures, but its accuracy has never been measured against matches it did not see,
and hard rule 8 says a model is wired in on its calibration rather than its reach. Table
tennis stays hand-written — its generic store holds 88 players against the 2,007 on
Setka's live index. Coverage is `data/results/` plus whatever passes its calibration. The generic gate now
admits ALL FIVE sports that have an adapter: football 0.012, basketball 0.028, tennis
0.012, baseball 0.014, table tennis 0.011. Football and table tennis still run their
hand-written models in production; both generic versions now out-evidence them, because
they have a held-out calibration and the bespoke ones do not, so replacing them is the
next thing to do after a side-by-side on one card.

Both of the sports that were refused turned out to be refused for a REASON THE GATE COULD
NOT SEE, and finding each took minutes once the gate pointed at them:
  * Table tennis had 27 results because the adapter read the collector's rolling window
    and not the 9,035-match archive sitting next to it. Nothing was broken; the adapter
    was pointed at one of two files.
  * Tennis mixed best-of-3 and best-of-5 into one distribution. A Bo5 match can finish
    3-0 in sets and a Bo3 one cannot, so "+2.5 sets" is two different bets, and the pooled
    record contained outcomes neither format could produce. `pool` now separates them.
That is what a refusal is for: it does not say the sport is unmodellable, it says stop and
look.

Sources checked and REFUSED on robots grounds while doing this, all by our crawler's name:
NHL (`api-web.nhle.com`, `api.nhle.com`), OpenDota, Liquipedia, bo3.gg's `/api/`, ESPN,
cbv.com.br. Allowed and used: football-data.co.uk, api-live.euroleague.net,
raw.githubusercontent.com (TML tennis), statsapi.mlb.com.

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
   **The score IS the model's win probability**, discounted toward the floor when the
   evidence is thin: `puan = 100 × (floor + (p − floor) × evidence)`. It was first built
   as a position in a band — 70 points of "how far past the floor" plus 30 of evidence —
   which is defensible arithmetic and an unreadable number: a 75.8% selection scored 28,
   and 28 reads as "the model is 28% sure", the opposite of its meaning. A score must mean
   ONE thing to the person reading it. Evidence = name-match strength, matches behind the
   division, sample behind the rating bucket; the discount is reported in points so it can
   be argued with. Scores necessarily cluster just above the floor — that band IS the
   product, and stretching it would invent a difference between 91% and 93% the model
   cannot support. Selections are numbered 1..N by score, once across the whole card, so a
   bet keeps the same number in both windows.
7. **Only emit what settles the same day.** Outrights are dropped structurally (an entry
   with no second participant is not a head-to-head, which also removes tournament
   winners, election questions, novelty bundles and multi-runner races in one rule), and
   sports whose head-to-heads span days sit in `config.MULTI_DAY_SPORTS`. Do NOT filter
   on the start timestamp for this: long-dated markets carry a near-term start. The 2026
   Senate markets are stamped 5–16 days out because that is when the LINE runs.
8. **A model that is confident is not a model that is right.** Every sport's model must be
   CALIBRATED against observed outcomes before it is wired in — predicted rate against
   realised rate, at the lines the ladder actually selects. Basketball's first fit had a
   sign error and claimed 90.4% for a +12.5 handicap where the real rate was 74.9%. Nothing
   about that number looks wrong, and it clears `MIN_MODEL_SURVIVAL` comfortably: the
   confidence floor CANNOT catch this class of error, because the floor trusts the model.
   Table tennis was caught the same way (extrapolating a logistic past its fitted range to
   97% on a 3.30 shot). The calibration must be HELD OUT: the first generic version scored
   predictions and outcomes from the same matches and reported a gap of 0.000 on every
   line, which is an arithmetic identity dressed as a test. `model_generic.usable()` is the
   gate — under 400 results, no calibration table, or a gap over 0.03 and the sport is
   refused. Ratings must be taken AS THEY STOOD BEFORE the match: fitting on final
   ratings describes a fixture by how good both sides turned out to be over the whole
   history, including that match and everything after it. That single leak was the largest
   error in the generic model — football went from a 0.043 gap to 0.010 with nothing else
   changed. A rating with fewer than `MIN_APPEARANCES` matches behind it prices nothing:
   1500 means "not measured", not "average", and treating it as average made every
   mismatch look like a coin flip. A variant marker — U20, (Women), B, reserves — makes a
   side a DIFFERENT team, not a fuzzier match: the generic matcher dropped that guard when
   it was generalized and immediately priced "Corinthians Paulista (Women)" off the MEN'S
   Brazilian Serie A, calling a +6.5 handicap 99.78%. Four of the model's most confident
   selections that day were the wrong team.
9. **RNG markets never enter the ranking.** Lottery measured a 3.09% median hold against
   football's 8.65%, so left in they head every run. No model can ever justify one.
   `config.EXCLUDED_SPORTS`.
10. **Qualify a source on its BODY, never its status code.** Learned repeatedly and the
   hard way: a 200 has been a Cloudflare block page, an Incapsula interstitial, a
   proof-of-work challenge, an empty array, a "we're renovating" placeholder and a 404
   page with a 257 KB body. Read the bytes.
11. **Check robots.txt for OUR crawler by name before fetching.** ESPN disallows
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
