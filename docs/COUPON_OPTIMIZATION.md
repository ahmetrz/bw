# COUPON_OPTIMIZATION.md

## The pipeline, in order

```
picks (football+tennis, from the SAME model layer the daily-picks path uses)
  -> engine.confidence.annotate()      full ConfidencePrediction per pick
  -> engine.combine.eligible()         hard gates (see below) — yes/no, not scored
  -> engine.referee.review_all()       10 judges; any veto removes the leg
  -> engine.combine.optimize()         beam search over what survives the board
  -> engine.coupon.create()            UNCHANGED — mints the actual slip code
```

## Hard gates (`engine/combine.eligible`) — before anything is scored

1. Sport in `config.COMBINE_SPORTS` (`{1, 4}` — football, tennis; the brief's explicit
   scope, section 3).
2. `confidence_score >= config.MIN_COMBINE_CONFIDENCE` (80.0) — see
   `docs/DECISIONS/0003-two-thresholds-not-one.md` for why this is a SEPARATE number from
   the daily-picks path's 0.75 floor, not a reconciled one.
3. Data quality does not block (`dataquality.assess()["blocks_combine"]`).
4. Fixture has not started (`start` parsed and compared against the run's `now`).
5. `odds >= config.MIN_ODDS` (1.10 — the SAME gate the rest of the product uses, re-checked
   here independently rather than trusted blindly from upstream).

## The optimizer's objective, and why it is not simpler

The brief explicitly rules out the simplest approach — "Basitçe tüm 80+ seçimlerin
oranlarını çarpmak profesyonel optimizasyon sayılmaz" — and asks for a genuinely
multi-objective search. `engine/combine._objective()`:

```
0.35 × avg_confidence  +  0.25 × combined_probability
  +  0.20 × sqrt(n)/sqrt(50)  +  0.15 × log(total_odds)/log(50)
  −  0.15 × correlation_penalty
```

- **`combined_probability`** is the product of each leg's `model_survival` — legs treated
  as independent. This is a stated simplification (`config.py`'s own comment on
  `MIN_COMBINE_COMBINED_PROBABILITY`), not a claim of true independence; real correlation
  is instead flagged by `engine/referee.correlation_judge` and penalised in the objective,
  because modelling the true joint distribution would need a correlation model this
  platform does not have.
- **`sqrt(n)`** gives more legs diminishing (not flat, not zero) reward — enough to prefer
  more matches when the probability cost is small, not enough to justify padding.
- **`log(total_odds)`** likewise rewards a higher combined price with diminishing returns,
  so the search cannot be dominated by chasing one long-odds leg.
- A **hard floor**, `config.MIN_COMBINE_COMBINED_PROBABILITY` (0.15), prunes any partial
  combine below it during the search — this is the literal mechanism behind "toplam oranın
  yükselmesi için kuponun gerçek başarı ihtimalini anlamsız seviyeye düşürme." 0.15 was
  chosen as roughly ten legs at the 80-floor's own probability neighbourhood (~0.83^10 ≈
  0.155) — documented in `config.py`, not asserted here without a number behind it.

## Why beam search over the alternatives the brief names

- **Brute force** (every subset) is 2^n; a realistic day's eligible pool can be several
  dozen legs.
- **A single greedy fill** (sort by confidence, add until the floor breaks) cannot trade a
  marginal 15th leg against the probability it costs — it can only accept-in-order.
- **Integer programming** finds a provably optimal solution for a *linear* objective; this
  one is deliberately non-linear (log/sqrt terms, a multiplicative floor), so IP's strength
  does not apply directly without linearising it, which would lose the diminishing-returns
  shape the brief asks for.
- **Beam search** (`config.COMBINE_BEAM_WIDTH = 8`) keeps a bounded set of the best partial
  combines at each step, letting a leg be skipped now and reconsidered in a different
  combination — verified against brute force on small candidate pools during this session
  (exact match every time tested).

## What the report shows (`combine.json`, `combine.html`, the PDF)

Every field the brief's section 15 asks for: `leg_count`, `combined_odds`,
`combined_probability` + a heuristic `combined_probability_band` (propagated from each
leg's own evidence discount — documented as a heuristic, not a rigorous statistical
interval, since no closed form fits the discounted-Elo/Laplace-capped pipeline cleanly),
per-leg contribution (`legs[].confidence`), `borderline` (referee-approved but not selected
— with the reason: probability floor, not quality), `vetoed` (with each veto's judge and
reason), and `why` (a plain-language summary of the search's own decision).

## Settlement — the gap nothing else in the codebase filled

`engine/grade.py` grades one leg. Nothing settled a WHOLE accumulator before this session.
`engine/combine.settle_combine()`:

- any `LOSS` leg → the whole combine loses (multiplier 0.0);
- a `PUSH` leg is removed from the odds product (contributes ×1.0);
- a `HALF` leg (quarter-line, half-stake decided) contributes `(odds + 1) / 2` — half the
  notional stake won at the leg's price, half pushed;
- any leg still pending → the whole combine stays pending, no partial verdict.

This is the standard industry accumulator convention, used here because Betwinner's own
push/void behaviour **inside one multi-leg slip** is explicitly unverified
(`engine/settlement.py`'s `OPEN_QUESTIONS`) — `needs_confirmation` is set to `True`
whenever a push/half leg is involved, exactly the same epistemic honesty
`engine/settlement.py` already applies to single legs.
