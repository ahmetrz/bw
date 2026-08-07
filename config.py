"""Football+tennis daily combine platform configuration. Single-book mode — no reference
book, no value/"beat the sharp" claim. Ranks and gates within Betwinner's own prices only
(docs/PRODUCT_VISION.md, hard rule 6).

Historical note (docs/DECISIONS/0001, 0007): this file used to carry a SECOND section for
a multi-sport top-N scanner (scan.py) that ran alongside this platform, sharing the engine
below. That product was retired and its scope-widening config (which tournaments to pull
for it, its own composite-score weights and odds band, its own diversity cap) was removed
with it — everything below is now the whole configuration surface, for the one product.
"""

# Sports that must never enter the ranking, because their prices carry no forecastable
# information AND they are cheap enough to dominate a sweep. Applied at FETCH time
# (tools/fetch_window.py), before config.COMBINE_SPORTS narrows further to football+tennis
# — cheap insurance against ever pulling this class of market at all.
#
# This is not a taste judgement, it is a measured hazard. On a live pull Betwinner's
# LOTTERY markets came back at a 3.09% median hold against football's 8.65% — RNG draws
# priced roughly three times cheaper than actual sport. A lottery draw's past outcomes
# tell you nothing about the next one, and the book can compute its exact odds as well as
# we can, so there is no asymmetry to find (hard rule 9).
EXCLUDED_SPORTS = {
    82,   # Lottery — RNG draws. Measured 3.09% median hold, the cheapest on the book.
    69,   # Toto — pool betting on Betwinner's own pool; the decisive input is the crowd's
          #        entry distribution, which is never published. One draw in four is a
          #        simulated football match rather than a real one.
    314,  # Polybet — crypto price derivatives, not a sporting event at all.
    87,   # Special Bets — one-off novelties. n=1 events have no repeatable structure to
          #                model and nothing to backtest against.

    # Long-dated markets. Excluded at the operator's instruction: a bet that takes months
    # to settle ties up the slip and returns nothing in the meantime, whatever its price.
    202,  # Politics — election questions. Note the start timestamp does NOT reveal how
          #            long-dated these are: the 2026 Senate markets are stamped 5 to 16
          #            days out, because that is when the LINE runs, not when the seat is
          #            decided. Filtering on the start time would have missed them.
    132,  # Horse Racing AntePost — ante-post by definition, and its stakes are normally
    133,  # Trotting AntePost      lost outright if the runner never starts, which is a
    151,  # Greyhound AntePost     different bet from the same price on the day.
}

# Outrights are dropped structurally rather than by listing sports, in engine/bwfeed.py:
# an entry with no second participant is not a head-to-head, so the one-selection-per-
# match rule has nothing to bind on and the safety ladder has no two-outcome market to
# walk down. That single rule catches tournament winners, season questions, novelty
# bundles and multi-runner races across every sport at once.

# --- Safety laddering ------------------------------------------------------
# The only place odds are allowed to influence selection. Direction comes from the
# model; the ladder then walks to the safest form of that same view and stops at the
# last rung still priced at or above this. A short price is NOT a probability estimate,
# so it must never be used to pick a side.
MIN_ODDS = 1.10

# The model must be THIS sure the leg survives before a selection is offered. Without a
# floor the ladder happily returns the safest available form of a coin flip, which is
# still a coin flip — it would just look conservative.
#
# Measured on survival, not on winning: a pushed leg is refunded at 1.00 rather than
# killing the coupon, so a whole-number handicap that refunds on an exact one-goal defeat
# really is safer than its win probability alone suggests, and finding that difference is
# the entire point of a safety ladder.
MIN_MODEL_SURVIVAL = 0.75

# Refuse markets that can return the stake instead of winning or losing outright.
#
# Three families can push: whole-number handicaps (+1 refunds on an exact one-goal
# defeat), quarter handicaps (+0.25 and +0.75 split the stake, so half of it can be
# returned), and whole-number totals (over 3.0 refunds on exactly three goals).
#
# Operator's call, and it tightens the product rather than loosening it: with pushes
# excluded the confidence floor becomes a floor on WINNING, not on merely surviving, so
# every remaining selection is a clean win-or-lose at the stated probability. A pushed leg
# on a coupon also pays 1.00, which quietly drags the combined return down without ever
# showing up as a loss.
ALLOW_PUSH_MARKETS = False

# --- Daily run --------------------------------------------------------------
# Windows reported each day. Both are pre-match only.
# ONE WINDOW, AND IT IS 24 HOURS. The list used to carry 48 as well, with 24 as a filter
# on the page. Operator's call, and it is the right one: a selection 40 hours out is not
# today's bet. Its price will move, its lineup is not known, and it reappears on tomorrow's
# card anyway — so the only thing the second window added was a longer list to read.
DAILY_WINDOWS_HOURS = (24,)

# --- Link resolution --------------------------------------------------------
# Betwinner is blocked in Turkey and rotates its public domain, so a hardcoded host is a
# link that eventually stops opening. This referral link is the stable entry point: it
# always lands on whichever mirror is currently live, and engine/mirror.py follows it to
# extract the host that the combine's own links are built on.
REFERRAL_URL = "https://bwref-l4ftkntp.com/13KD"

# --- Combine platform ---------------------------------------------------------
# Everything below governs tools/daily_combine.py, engine/combine.py, engine/referee.py
# and engine/confidence.py — the single-daily-combine product described in the platform
# brief (docs/PRODUCT_VISION.md). MIN_MODEL_SURVIVAL and MIN_ODDS above gate every
# candidate before it ever reaches this section; see docs/DECISIONS/0003 for why the
# 0.75/1.10 selection gate and the 80-point combine-confidence floor below are
# deliberately separate numbers rather than one reconciled threshold — a leg surviving
# the ladder's gate and a leg being confident enough to sit in a combine are different
# questions.
COMBINE_SPORTS = {1, 4}          # football, tennis — the brief's explicit scope (section 3)

# The brief's own minimum, applied to engine/confidence.py's confidence_score (the SAME
# 0-100 number rating.py already computes — never a second, looser score invented to make
# 80 easier to reach).
MIN_COMBINE_CONFIDENCE = 80.0

# A combine's legs are treated as independent for the combined-probability estimate —
# engine/combine.py's own product of each leg's model_survival, a MODEL quantity, not a
# book one (docs/COUPON_OPTIMIZATION.md) — a simplification, not a claim of true
# independence; real correlation is instead FLAGGED by engine/referee.correlation_judge
# and penalised in the optimizer's objective, rather than modelled exactly, because
# modelling it exactly would need a joint outcome model this platform does not have.
#
# The floor below is what stops leg-count or total-odds growth from hollowing out the
# combine's own real chance of winning (the brief's explicit "toplam oranın yükselmesi
# için kuponun gerçek başarı ihtimalini anlamsız seviyeye düşürme"): ten legs at the 80
# floor's own probability neighbourhood (~0.83-0.85 typical) multiply out to roughly
# 0.83^10 ≈ 0.155, so 0.15 is set as the point below which adding one more leg is refused
# regardless of how attractive that leg looks alone.
MIN_COMBINE_COMBINED_PROBABILITY = 0.15

# Beam search width for engine/combine.optimize() — see that module for why beam search
# rather than a simple greedy fill or brute-force subset search (2^50 candidates on a full
# card). A wider beam costs more computation for a marginally more thorough search; 8 was
# enough on every fixture-based test to match brute force on candidate pools up to 20.
COMBINE_BEAM_WIDTH = 8

# Correlation concentration cap used by engine/referee.correlation_judge — see that
# function. Per LEAGUE across a whole combine of one-pick-per-match legs: two legs from
# the same competition are more likely to share a common cause (a weather system, a
# refereeing pattern, a round of fixtures playing short-handed) than two from unrelated
# ones, so this bounds how much of one combine's story can come from a single league.
COMBINE_MAX_LEAGUE_SHARE = 0.40
