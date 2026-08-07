# CLAUDE.md — Football & Tennis Daily Combine Platform

## What this project is
A **single-book, two-sport** decision-support platform for Betwinner. Once a day it
either produces **one combine** — a small, ten-judge-reviewed, multi-objective-optimized
accumulator across independent football and tennis matches, each scored 0–100 with full
auditable reasoning — or it says plainly that no combine cleared the bar that day. There
is **no reference book** and the tool makes **no value/"beat the sharp" claim** — every
gate, score and judgement is computed within Betwinner's own prices. It emits a report
and a bet-slip code; it does not place bets, and it does not size a bankroll (see "How
much to bet" below).

Until 2026-08-07 this repo also ran a second, older product — a multi-sport top-N scanner
(`scan.py`) and its own daily picks list, covering roughly thirty sports. It was retired,
not kept alongside the combine platform: `docs/DECISIONS/0007` records why and exactly
what was removed. Scope is now fixed at football (Betwinner `sport_id=1`) and tennis
(`sport_id=4`) — not "every sport a model can reach," a deliberate, reversible product
decision, not a capability that was lost.

## Trigger → Transformation → Output
- **Trigger:** the DAILY run (`.github/workflows/combine.yml`, targeting 07:00 Istanbul —
  04:43 UTC, with 05:43/06:43 UTC backstops, operator-approved cadence) fetches the next
  **24 hours** of Betwinner's pre-match card via GitHub Actions; the operator's machine
  blocks the site. The backstops check `data/combine_log.jsonl` FIRST and exit before
  rewriting anything — a later run that rebuilt the combine would hand over a different
  plan from the one that was announced, with fresh prices and a new slip code.
- **Transformation:** normalize → restrict to football+tennis → model assigns a DIRECTION
  → ladder converts it to its safest form → odds gate at 1.10 → confidence floor →
  one selection per match → data-quality score → confidence score (0–100, model
  probability discounted by evidence) → ten-judge referee board (any veto kills a leg) →
  multi-objective combine optimizer (beam search) → bet-slip code, verified before it is
  handed over. See "The daily rule, in order" below for the full ordering, and
  `docs/REFEREE_BOARD.md` / `docs/COUPON_OPTIMIZATION.md` for the last two stages.
- **Output:** `combine.json` + `combine_report.pdf` + 14 self-contained, filterable HTML
  pages (`tools/make_platform_pages.py`), sent to the existing Telegram channel as an
  attachment (the PDF) with a SHORT notice as its caption
  (`tools/notify_combine.py`) — the same reasoning this project has always applied to a
  daily notice: it should say that today's analysis exists and how it looks, not carry
  the whole thing itself. `data/combine_log.jsonl` is the permanent, append-only record —
  one row a day, written whether or not a combine was produced, because "no combine
  today" is a valid and common outcome, not a failure to log.
- **Result loop:** `.github/workflows/results.yml` runs **hourly** (:30). It settles
  whatever legs have finished (`tools/grade_combine.py` — a combine settles only once
  EVERY leg has an individual result, never partially), refreshes the bet-slip code from
  legs that have not started (`tools/refresh_combine.py` — a slip is a live object, not a
  document; the book rebuilds it the moment one leg kicks off, silently changing its bet
  type), and rebuilds the 14 platform pages. Hourly because a leg's outcome is known when
  it ends and the sources now say so within the hour — the live watcher records a match
  as it finishes, flashscore carries ~570 football results through the day,
  tennisexplorer publishes the same day's sets.
- **The record across days:** the platform pages include a calibration/track-record view
  (`engine/track_record.py`) built from `data/combine_log.jsonl` plus the per-sport
  calibration already carried on each model file. One day is a handful of legs and its
  hit rate swings on noise; the cumulative number is the only one with authority. See
  `docs/PERFORMANCE_METRICS.md` and `docs/SELF_LEARNING.md`.
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
    trim has to happen before the call. `coupon.MAX_EVENTS`.
  * **One selection per event.** Two outcomes on one `GameId` — two lines of a market, or
    its two sides — come back as ONE leg with `HasRemoveEvents` set. The book does not
    refuse, it silently keeps the first and drops the rest, which is how a slip claims
    fifty and delivers forty-nine. `engine/pick.py` already emits one pick per match, so
    the dedup in `coupon.create` should never fire; it is there because the failure is
    silent.
  * **`IsBannedExpress`** — the book's own per-leg flag for "may not be in an accumulator".
    **`IsRelation`** — dependent events. **`Block`** — suspended. None of the three appear
    on the pre-match card; they exist only in the coupon read-back, which is where
    `coupon.BANNED_FLAGS` reads them.
  * **A started fixture is dropped and the slip REBUILT**, not filtered — which is why a
    code cannot be minted once with the morning combine. `tools/refresh_combine.py`
    rebuilds it hourly, alongside grading, from legs that have not started. Codes also
    expire outright: every one minted three days ago now answers "Incorrect code".
  * **The bet type cannot be set at all.** `Vid` looked like a clean enum — on three legs
    whose product was 1.4705, `Vid=1` returned exactly that, `Vid=3` returned 1.414, and
    `Vid=2` returned 0, which is what a set of singles has. It is not: pushed to forty legs
    the service names them itself, `Vid=2` and `Vid=4` answering *"Invalid number of events
    in System bet"* while every other value is stored as 1. So `Vid=2` is a SYSTEM bet
    whose combination was invalid. For THIS product that finding is informational rather
    than a warning to display: the combine platform's own slip is meant to load as an
    accumulator — that is the product — so there is nothing to switch it away from.
  * Not readable to us: the book's written rules. `/en/rules` and every guessed path 404s,
    the sitemap carries no rules entry, the site footer links only to bonus rules, and the
    full rulebook lives on `betwinner2.com`, whose robots.txt is `Disallow: /`. Everything
    above therefore comes from the API's own behaviour, which is the stronger evidence
    anyway — it is what the slip will actually do.
- **How much to bet:** this product does not size a bankroll and does not recommend a
  stake. `engine/combine.py`'s `COMBINE_STAKE_UNITS` is a flat, analytical-only constant
  used solely to express the combine's own figures (expected-return multiple, break-even
  rate) on a consistent 1-unit basis — never a position-sizing recommendation, and never
  read from the model's own confidence: doing that would convert "the model is 86% sure"
  into "the model is 86% sure AND the book is wrong about it" and size a bet on a claim
  the product never makes out loud. The reported figures are the combine's own
  book-implied numbers (`combined_odds`, `combined_probability`,
  `MIN_COMBINE_COMBINED_PROBABILITY`), which assert nothing beyond arithmetic on the
  book's own prices, sitting beside the realised settlement — never beside the model's
  confidence, which is the thing under test.

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
   still walks down to the next clean rung rather than dropping the match.
6. **Data quality and confidence scoring** (`engine/dataquality.py`, `engine/confidence.py`)
   turn the surviving candidate into a reason-coded 0–100 data quality score and a full
   confidence report (EV, implied probability, factors, risks) — reporting layers on top
   of `engine/rating.py`'s score, never a second scoring path (hard rule 6 extended).
7. **The referee board** (`engine/referee.py`, ten deterministic judges, no external LLM)
   reviews every surviving candidate. Any veto kills that leg. `docs/REFEREE_BOARD.md`.
8. **The combine optimizer** (`engine/combine.py`, beam search) selects a genuinely
   multi-objective subset of the referee-approved legs — or none, which is a normal,
   first-class, expected-to-happen outcome (`docs/COUPON_OPTIMIZATION.md`).
9. **A minimum combined-probability floor** (`MIN_COMBINE_COMBINED_PROBABILITY`) stops
   leg-count or total-odds growth from hollowing out the combine's own real chance of
   winning.

A match where the model has no confident view yields NOTHING. Padding the combine with
the least-bad option available would defeat the whole exercise, and "no combine today"
must be a valid, common outcome — never something the pipeline works around.

## Architecture
```
tools/daily_combine.py    entrypoint: fetch -> normalize -> pick -> settle -> confidence
                           -> referee -> combine -> coupon -> Telegram notice ->
                           data/combine_log.jsonl -> combine.json
tools/notify_combine.py   sends combine_report.pdf to the existing Telegram channel with
                           a short caption built from combine.json (a separate step from
                           daily_combine.py, which runs before the PDF exists)
tools/grade_combine.py    settles data/combine_log.jsonl once results are known
tools/refresh_combine.py  rebuilds today's bet-slip code hourly from legs that have not
                           started (a slip is a live object, not a document)
tools/make_pdf_report.py  combine.json -> combine_report.pdf (reportlab + vendored font)
tools/make_platform_pages.py  the 14 web screens, from combine.json + governance data
tools/webshell.py         shared shell/CSS/escaping for the 14 screens
tools/check_source_health.py  probes catalogued data sources, writes data/source_health.json
tools/fetch_window.py     sports -> tournaments -> fixtures -> markets, budgeted+checkpointed
tools/collect_results.py  one small adapter per source -> the results store (football,
                           TML tennis, tennisexplorer — narrowed to the product's own scope)
tools/collect_live.py     watches the book's OWN live feed for football and tennis
tools/build_generic_model.py  fits + calibrates any sport; refuses the ones that fail
tools/build_football_model.py fits the (currently dormant, see engine/pick.py) Elo model
tools/telegram_ping.py    credential pre-check, run before the daily fetch
tools/heartbeat.py        says something when today's combine run did not happen at all
engine/bwfeed.py          Betwinner feed -> normalized rows (market keying, coverage)
engine/pick.py            direction + ladder + gates -> one selection per match
engine/ladder.py          safety laddering; three-way vs two-way read off the payload
engine/rating.py          the 0-100 score = model probability, discounted by evidence
engine/dataquality.py     reason-coded 0-100 data quality score per pick
engine/confidence.py      wraps rating.score() into the full confidence report (EV,
                           implied prob, factors, risks, model version)
engine/referee.py         ten deterministic judges + two board-level judges
engine/combine.py         eligible() -> referee -> optimize() (beam search) -> report
engine/governance.py      ProposedModelChange records + model-version archiving
engine/track_record.py    Brier score, log loss, per-sport calibration, gradeability
engine/model_generic.py   ONE model for every sport, counted from the results table
engine/model_football.py  ClubElo lookup + shared scoreline builder (model_elo.py's)
engine/model_elo.py       hand-written football Elo model — fitted, currently unused by
                           pick.py (MODELLED_SPORTS is empty), kept for fast re-admission
engine/results_store.py   ONE results table per sport: date, teams, score. Nothing else.
engine/settlement.py      what a selection actually means when it settles
engine/coupon.py          the day's plan as ONE bet-slip code, verified before handoff
engine/parlay.py          betwinner_url() only — deep links, shared by everything
engine/telegram.py        Telegram delivery (no-ops without credentials)
engine/tr.py              Turkish labels for everything user-facing
engine/simulated.py       flags physically-impossible ("generated") competitions
config.py                 gates, weights, exclusions, windows — one product's worth
research/                 per-sport statistics, free sources, rules traps
fixtures/                 real pulls = regression anchors
docs/                     see docs/ARCHITECTURE.md for the full documentation index
```

## Secrets
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub Actions secrets — the same bot and
channel this project has always used; no second bot was set up for this product. Their
absence is NOT an error: the run still fetches, still scores, still writes `combine.json`,
and reports the send as skipped. A credential problem must never fail a run that
otherwise worked.

## Confidence and data-quality scoring
Replaces what an earlier, now-retired product here called "the composite score" (a
within-book cheapness ranking on margin/limit/range — see `docs/DECISIONS/0007` for why
that product is gone). This product's score is not a ranking signal at all; it is the
model's own claim, made legible and discounted where the evidence is thin.

1. **The 0-100 score IS the model's win probability**, discounted toward the floor when
   the evidence is thin: `puan = 100 × (floor + (p − floor) × evidence)`
   (`engine/rating.py`). Evidence = name-match strength, matches behind the division,
   sample behind the rating bucket. A score must mean ONE thing to the person reading
   it — see hard rule 6 below; this is the invariant most likely to be violated by
   accident, because sorting by short prices looks like sorting by safety and is not.
2. **`engine/dataquality.py`** turns the same evidence signals into a reason-coded 0-100
   data quality score with 8 fixed reason codes, decomposed rather than recomputed
   differently from `rating.py` — a thin sample shows up in both, for the same reason.
   `docs/DATA_QUALITY.md`.
3. **`engine/confidence.py`** wraps `rating.score()` (UNCHANGED) into the full
   `ConfidencePrediction` contract the platform reports: expected value, implied
   probability, factors up/down, risks, model version. Reporting only, never a second
   scoring path. `docs/CONFIDENCE_SCORING.md`.

## Sport scope is fixed at football and tennis
Not "every sport a model can reach" — a deliberate product decision
(`docs/DECISIONS/0007`), reversed from an earlier session where the intent was the
opposite ("adding a sport" used to be a routine, expected-to-grow procedure; it now
requires a scope decision, not just a calibration pass). What follows describes how
football and tennis themselves are modelled and kept honest, which is still an ongoing,
routine concern within that fixed scope.

Both sports run on `engine/model_generic.py` — `pick.MODELLED_SPORTS` (the list of
HAND-WRITTEN models) is empty. Football's hand-written Elo model left it earlier this
session: it reaches more fixtures but has never been measured against matches it did not
see, and hard rule 8 says a model is wired in on its calibration, not on its reach — the
generic model's 0.010 held-out gap is what actually qualifies. Table tennis's
hand-written model (Setka ratings) left with the sport itself when scope narrowed. The
dormant Elo branch in `pick.resolve()` is kept, not deleted, so re-admitting it is a
one-line change if a future comparison ever favours it.

**The generic model's admission gate is unchanged and still does its job.** Football
clears at 0.010, tennis at 0.023 (both `MIN_APPEARANCES`-gated, both held out
chronologically — `docs/TENNIS_MODELS.md` has the full diagnostic history for tennis,
including the date-proportional calibration-split fix and its disclosed side effect on
basketball, which is refused today not because it is out of scope but because it fails
its own calibration under the current split). A sport failing calibration is refused
exactly the same way whether or not it is in `config.COMBINE_SPORTS` — the gate does not
know or care what the product's scope is, which is what makes it trustworthy.

## Where results come from
The live watcher (`tools/collect_live.py`) is the default source for both sports it
watches. `LiveFeed/Get1x2_VZip` carries both names, both STABLE participant ids, the
running score, the period breakdown and the FORMAT note. Two ways a match gets written
down, and the first is far better than the second:
  1. **The feed says so** — `SC.CPS` becomes "Match finished". Nothing is inferred.
  2. **It vanished**, and the state it was last seen in says the match was over. For
     tennis (a RACE) that is the score, read against the format and never assumed: tour
     tennis runs best-of-three and best-of-five on the same day with no format note
     published at all, so 2-0 is a finished match in one and a lead in the other. For
     football (a PERIOD sport) the score can never say it — 1-0 in the second half looks
     exactly like 1-0 at full time — so what says it is the CLOCK: `SC.TS` counts up to
     regulation and stops, and `SC.SLS` ("84 minutes") goes EMPTY at the same moment.
It refuses a sport whose finish condition we cannot state (which is why `SPORTS` is a
list of finish CONDITIONS, not of sports Betwinner happens to run), an unreadable format,
and anything gone too briefly to be sure it is gone. A watcher that guesses is worse than
no watcher: a wrong row is indistinguishable from a real one once it is inside a rating.

**Archives fill in what the live watcher cannot have collected yet.** Football:
football-data.co.uk (season CSVs, checked against robots.txt by our crawler's name,
2026-07-26) plus flashscore's own feed as a grading-only fallback (never written to the
results store — its competition names would fragment football-data's division pools for
no gain). Tennis: TML-Database (`raw.githubusercontent.com`, six months stale at any
given time) plus tennisexplorer.com (current, but abbreviated names — bridged by
`grade_predictions.lookup_abbrev`, the LAST route tried so a weaker identification never
displaces the book's own ids). Full source-by-source detail, including sources checked
and refused on robots grounds, is in `docs/DATA_SOURCES.md` — kept there rather than here
because the list of sources this product no longer reaches (basketball, table tennis,
baseball) is historical record, not operating instruction.

There is deliberately no step for writing a bespoke model for either sport.
`engine/model_generic.py` counts what happened instead of assuming a distribution, so
both a fat-draw sport and a cannot-draw one work with the same code — see "Sport scope"
above for the calibration numbers.

## Hard rules (engineering invariants — do not violate)
Numbering is preserved from before `docs/DECISIONS/0007` where the rule's content
survives, even where its *text* changed — several rules described the now-retired
scanner specifically, and renumbering would have broken every cross-reference to a hard
rule by number across `docs/`, the test suite, and the ADRs themselves.

1. **Every emitted selection carries the fields `docs/CONFIDENCE_SCORING.md` and
   `docs/DATA_QUALITY.md` specify** — odds, settlement, the confidence report, the data
   quality score and its reasons, the referee verdict. A row missing any of these is a
   bug. (The scanner's own field list — margin_score, limit_score, range_score,
   total_score, market_overround — described a within-book cheapness ranking this
   product does not compute; see `docs/DECISIONS/0007`.)
2. **SUPPRESS (never emit):** market or outcome inactive; `changedAt` older than the
   staleness window. Alt lines are NOT suppressed here the way an earlier, now-retired
   product suppressed them — the safety ladder needs alternative lines to find the
   safest rung, and every plus-handicap and non-headline total IS an alt line.
3. **Default deliverable is ONE combine a day, or an honest "no combine today."** Not a
   top-N list — that was the retired product's shape, not this one's.
4. **The combine's own numbers are never presented as positive value.** Because there is
   no reference, a combine can only be described in the book's OWN implied numbers:
   combined decimal odds, combined book-implied probability, and
   `MIN_COMBINE_COMBINED_PROBABILITY` as the floor below which adding one more leg is
   refused regardless of how attractive it looks alone. By construction within one book
   this cannot carry positive expectation, and nothing here presents it as if it could.
5. **Never fabricate odds or limits.** If the loaded data's book ≠ the requested book,
   or the API 4xx's, STOP and report — never proceed on fallback data.
6. **Direction never comes from the price.** This is the one invariant most likely to be
   violated by accident, because sorting by short prices looks like sorting by safety
   and is not. The **0-100 score obeys the same rule**: `engine/rating.py` reads model
   survival and evidence quality only, and a test asserts the score does not move when
   the odds change. A score that quietly folded the price back in would rank by the
   book's opinion while looking like analysis — and it would go unnoticed for weeks,
   because a short price and a confident model agree often enough. See "Confidence and
   data-quality scoring" above for the full statement.
7. **Only emit what settles the same day.** Outrights are dropped structurally (an entry
   with no second participant is not a head-to-head, which also removes tournament
   winners, election questions, novelty bundles and multi-runner races in one rule).
   Football and tennis both settle within hours, so no multi-day-sport exclusion list is
   needed for the product's current scope — if that scope ever widens, a sport whose
   head-to-heads can span days needs the same exclusion the old `config.MULTI_DAY_SPORTS`
   provided, re-added deliberately rather than assumed unnecessary.
8. **A model that is confident is not a model that is right.** Every sport's model must
   be CALIBRATED against observed outcomes before it is wired in — predicted rate
   against realised rate, at the lines the ladder actually selects. Basketball's first
   fit had a sign error and claimed 90.4% for a +12.5 handicap where the real rate was
   74.9%. Nothing about that number looks wrong, and it clears `MIN_MODEL_SURVIVAL`
   comfortably: the confidence floor CANNOT catch this class of error, because the floor
   trusts the model. The calibration must be HELD OUT, chronologically (train ending
   before test begins, checked directly — not via a row-count proxy, which stopped
   holding once the calibration split went date-proportional; see
   `docs/TENNIS_MODELS.md`). `model_generic.usable()` is the gate — under 400 results, no
   calibration table, or a gap over 0.03 and the sport is refused. Ratings must be taken
   AS THEY STOOD BEFORE the match: fitting on final ratings describes a fixture by how
   good both sides turned out to be over the whole history, including that match and
   everything after it — football went from a 0.043 gap to 0.010 with nothing else
   changed by fixing exactly this. A rating with fewer than `MIN_APPEARANCES` matches
   behind it prices nothing: 1500 means "not measured", not "average". A variant marker
   — U20, (Women), B, reserves — makes a side a DIFFERENT team, not a fuzzier match.
9. **RNG markets never enter the pipeline.** Lottery measured a 3.09% median hold against
   football's 8.65%, so left in they would head every ranking a within-book cheapness
   product ever computed. No model can ever justify one. `config.EXCLUDED_SPORTS` filters
   these at fetch time regardless of whether the product's own scope (football+tennis)
   would ever have reached them anyway — cheap insurance against ever pulling the class
   of market at all.
10. **Qualify a source on its BODY, never its status code.** Learned repeatedly and the
    hard way: a 200 has been a Cloudflare block page, an Incapsula interstitial, a
    proof-of-work challenge, an empty array, a "we're renovating" placeholder and a 404
    page with a 257 KB body. Read the bytes. `tools/check_source_health.py` does this for
    every catalogued source, daily.
11. **Check robots.txt for OUR crawler by name before fetching.** ESPN disallows
    `anthropic-ai`; several sources name `ClaudeBot`. A source already recorded as
    verified can become disallowed later — checked again, not assumed permanent.

## Human-in-the-loop intervention points
1. **Model governance** — structural changes (weights, thresholds, calibration method,
   which model is authoritative) are proposed (`engine/governance.propose()`), never
   auto-applied, and require an explicit human `review()` decision before the actual code
   change is made. Routine data refits are NOT this — see `docs/MODEL_GOVERNANCE.md` for
   the distinction and `docs/DECISIONS/0004`.
2. **Cadence and quota** — before widening what a scheduled workflow fetches or how
   often, the operator approves it. Both daily schedules in this repo
   (`combine.yml`, `results.yml`) are already at operator-approved cadences; changing
   them is a cadence change, not a code change.
3. **Sport scope** — adding a third sport, or reversing this session's narrowing, is a
   product decision (`docs/DECISIONS/0007`), not something to do because a sport happens
   to clear `model_generic.usable()`. Calibration is necessary for admission; it was
   never sufficient on its own for scope.
