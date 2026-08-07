# PERFORMANCE_METRICS.md

The metrics this platform reports, where each is computed, and what it is (and is not)
allowed to imply. Read `docs/SELF_LEARNING.md` first — this document is the reference list
that one narrates.

| Metric | Function | Good direction | Minimum sample before shown |
|---|---|---|---|
| Hit rate (decided legs) | `engine/grade.summarize()` | higher | `MIN_MEANINGFUL=20` (`engine/track_record.py`) |
| Combined odds (reference, not a target) | `engine/combine.py`'s `combined_odds` — pure arithmetic on the book's own per-leg prices | — | none |
| Combined probability floor | `engine/combine.py`'s `combined_probability` (product of each leg's `model_survival` — the combine's own estimate, not book arithmetic, `docs/COUPON_OPTIMIZATION.md`), gated at `config.MIN_COMBINE_COMBINED_PROBABILITY` | higher | none |
| Calibration gap (claimed − realised) | `engine/track_record.calibration_by_sport()` | closer to 0 | 20 graded per sport |
| Brier score | `engine/track_record.brier_score()` | lower (0 = perfect, 0.25 = coin-flip baseline) | none — reported with `n` alongside it |
| Log loss | `engine/track_record.log_loss()` | lower (0.693 = coin-flip baseline) | none |
| Market gradeability | `engine/track_record.market_history()` | higher (fewer stuck-pending) | 20 old-enough predictions per market |
| ROI (analytical only) | `engine/grade.summarize()`'s `roi_pct`, `engine/combine.COMBINE_STAKE_UNITS` | — | never tied to real money, brief's explicit instruction |

## The one non-negotiable pairing

Hit rate is never shown next to the model's own claimed confidence without the calibration
gap alongside it. Showing "92% average confidence, 88% hit rate" without also showing "−4
points, N=137" invites reading the gap as noise when 137 samples can distinguish it from
noise — the same reasoning the retired scanner's own `stats.html` used to apply
(`docs/DECISIONS/0007`), carried forward onto this platform's own numbers on `lab.html` and
`calibration.html`.

## What is deliberately not computed

- **A single blended "platform score."** Confidence, data quality, referee approval and
  historical calibration are reported as separate numbers because collapsing them into one
  index would hide exactly the disagreement between them that makes each one useful — a
  selection with high model confidence and low data quality is a DIFFERENT situation from
  low confidence and high data quality, and one number cannot say which.
- **Precision/recall as a headline.** See `docs/SELF_LEARNING.md`'s explanation — this
  product's structure (continuous probability, no fixed labelled negative set) fits
  Brier/log-loss more naturally.
- **Any metric computed on the combine's own legs alone with fewer than 20 samples.** The
  first several weeks of combines will not have enough settled history to populate
  `calibration.html` meaningfully, and the page says so plainly (`ws.empty_state`) instead
  of computing a number from three data points and presenting it with the same visual
  weight as a mature one.
