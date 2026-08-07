# PRODUCT_VISION.md

## What this is

A personal, single-operator decision-support platform for football and tennis. Every day
it either produces **one combine** (an accumulator of independently-vetted, high-confidence
selections across as many matches as the day's card genuinely supports) or it says plainly
that no combine cleared the bar. It never auto-bets, never handles real money, and never
claims a guaranteed or risk-free outcome.

It is the only product in this repo. It was originally built alongside, and on top of, an
older **Betwinner Odds Scanner** — a separate multi-sport product that ranked the book's
own markets by within-book cheapness and produced a daily top-N singles list across dozens
of sports (`docs/DECISIONS/0001-extend-not-replace.md`). That scanner has since been
**retired outright**, on the operator's own instruction: "Eski yapıyı ortadan kaldır.
Sadece tenis ve futbol olacak ve yeni yapı ile ilerleyeceğiz" (`docs/DECISIONS/0007-retire-
the-scanner-single-product.md`). `docs/DECISIONS/0001`'s "extend, don't replace" premise
described how this platform was first built; `docs/DECISIONS/0007` supersedes it — nothing
today shares this repo with the combine platform, and its scope (football+tennis, an
80-point confidence floor, a ten-judge review board, one combine or none) is simply the
product's scope, not one of two products' scope.

## What "serious" means here, concretely

Not a demo, not a random-pick generator, not a dashboard over fabricated numbers. Concretely:

1. **Every number traces to a real computation.** The confidence score IS the model's
   calibrated win probability, discounted by evidence — never a display artefact
   (`engine/rating.py`, hard rule 6, enforced by a test that asserts the score cannot move
   when only the price changes).
2. **A model is trusted on its calibration, not its authorship.** `engine/model_generic.py`
   refuses to price a sport whose held-out predictions disagree with its own observed
   history by more than 3 points (hard rule 8). Tennis failed that check for most of one
   session and was correctly refused rather than forced through; the underlying calibration
   split was then fixed, reviewed, and approved through governance, and tennis now clears
   the bar at a 0.023 gap — see `docs/TENNIS_MODELS.md` for the full before/after.
3. **Results are tracked and fed back.** `data/combine_log.jsonl` is this product's
   append-only, reproducible log; `tools/grade_combine.py` settles it against
   independently-sourced results, never against the model's own claim.
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
- Not a value-betting tool against a reference book. There is no second book and no
  "beat the sharp" claim; every gate, score and judgement is computed within Betwinner's
  own prices (`CLAUDE.md`, opening paragraph).
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
