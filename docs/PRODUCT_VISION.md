# PRODUCT_VISION.md

## What this is

A personal, single-operator decision-support platform for football and tennis. Every day
it either produces **one combine** (an accumulator of independently-vetted, high-confidence
selections across as many matches as the day's card genuinely supports) or it says plainly
that no combine cleared the bar. It never auto-bets, never handles real money, and never
claims a guaranteed or risk-free outcome.

It is built on top of, and does not replace, the existing **Betwinner Odds Scanner**
(`CLAUDE.md`) — a separate, already-live, multi-sport product that ranks the book's own
markets by within-book cheapness and produces a daily top-N singles list across dozens of
sports. Where the two overlap (both read Betwinner's card, both use the calibrated
per-sport model layer) they share code; where their products differ (one combine vs. many
singles, football+tennis vs. every sport, an 80-point floor vs. a 75-point one, a ten-judge
review board vs. none) they are kept deliberately separate. See
`docs/DECISIONS/0001-extend-not-replace.md`.

## What "serious" means here, concretely

Not a demo, not a random-pick generator, not a dashboard over fabricated numbers. Concretely:

1. **Every number traces to a real computation.** The confidence score IS the model's
   calibrated win probability, discounted by evidence — never a display artefact
   (`engine/rating.py`, hard rule 6, enforced by a test that asserts the score cannot move
   when only the price changes).
2. **A model is trusted on its calibration, not its authorship.** `engine/model_generic.py`
   refuses to price a sport whose held-out predictions disagree with its own observed
   history by more than 3 points (hard rule 8). This session found tennis currently failing
   that check and did not force it through — see `docs/TENNIS_MODELS.md`.
3. **Results are tracked and fed back.** `data/predictions.jsonl` and
   `data/combine_log.jsonl` are append-only, reproducible logs; `tools/grade_predictions.py`
   and `tools/grade_combine.py` settle them against independently-sourced results, never
   against the model's own claim.
4. **A combine can legitimately be nothing.** `engine/combine.py`'s search space always
   includes the empty combine, and it wins whenever nothing else scores higher — "kupon
   bulunamadı" is not a fallback UI state bolted on afterward, it is a normal branch of the
   same optimizer.
5. **Ten independent, deterministic judges can veto a selection.** No external LLM anywhere
   in the decision path (`engine/referee.py`) — every judge is arithmetic and lookups over
   numbers already computed elsewhere in the pipeline.

## What this product is explicitly NOT

- Not a guarantee. No screen, page, or report claims certain profit or a risk-free bet
  (master brief, hard prohibition).
- Not a value-betting tool against a reference book. There is no second book; the scanner
  it sits on top of ranks Betwinner's own prices against Betwinner's own prices
  (`CLAUDE.md`, opening paragraph).
- Not a staking or bankroll manager. `engine/combine.py`'s `COMBINE_STAKE_UNITS` is a flat
  analytical unit for computing a hypothetical ROI figure in the performance lab — never a
  real-money instruction, never connected to any account.
- Not an auto-bettor. `engine/coupon.py` produces a code the operator types into
  Betwinner's own "load bet slip" box by hand. Nothing in this repo, old or new, submits a
  bet.

## Who it is for

One person: the operator running this repo. The brief is explicit that the product is
single-user (section 2), and several licensing and scope decisions in this session
(`docs/DATA_LICENSING.md`) are only valid under that constraint — sharing this tool with
anyone else requires re-reading that document first, not just flipping a setting.
