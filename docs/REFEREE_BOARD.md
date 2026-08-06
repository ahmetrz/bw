# REFEREE_BOARD.md

Ten independent, deterministic checks over each candidate selection, run after the model
has already produced a confidence score and before `engine/combine.py`'s optimizer builds
the day's combine. **No external LLM anywhere in this module** (`engine/referee.py`) — the
platform brief requires this explicitly (section 14), and every judge below is arithmetic
and lookups over numbers other modules already computed.

A **VETO** from any single judge removes the leg outright — no vote-counting, no override
by consensus. This mirrors `engine/coupon.py`'s own posture toward the book's
`BANNED_FLAGS`: one disqualifying fact is enough regardless of how good everything else
looks.

## The ten judges

| # | Judge (`engine/referee.py` function) | What it actually checks | Can veto? |
|---|---|---|---|
| 1 | Veri Kalitesi (`data_quality_judge`) | `dataquality.assess()`'s 0-100 score | yes, below 40 or a critical reason |
| 2 | İstatistiksel Tutarlılık (`statistical_consistency_judge`) | required fields present, every probability inside [0,1] — the SHAPE of the evidence, never the price | yes |
| 3 | Pazar Güvenilirliği (`market_reliability_judge`) | `settlement.needs_confirmation` + historical gradeability of this market type (`track_record.market_history`) | flag only |
| 4 | Overfitting (`overfitting_judge`) | near-certainty (≥0.97) claimed on a thin sample (<1500) — the exact shape of two real bugs this codebase shipped once (basketball's sign error at 90.4%, table tennis's 97% extrapolation) | yes |
| 5 | Haber ve Güncellik (`recency_judge`) | odds staleness only — explicitly does NOT claim to have checked news/injuries, because no such source is integrated | flag only |
| 6 | Korelasyon ve Ortak Risk (`correlation_judge`, board-level) | league concentration (>40% of the combine from one competition), a participant appearing twice, over-reliance on one model source | flags legs, does not veto directly |
| 7 | Oran/EV (`odds_ev_judge`) | re-verifies `MIN_ODDS` independently (trust-but-verify); flags implausibly high EV as likely model error, never as a reason to prefer a leg | yes, below `MIN_ODDS` |
| 8 | Geçmiş Performans (`historical_performance_judge`) | claimed vs. realised hit rate for this SPORT, from `track_record.calibration_by_sport()`, gated at ≥20 graded samples | yes, if realised trails claimed by >10 points |
| 9 | Sonuç Doğrulanabilirliği (`result_verifiability_judge`) | can this sport's outcome actually be independently checked later (`results_store` coverage) — section 11's rule made concrete | yes |
| 10 | Nihai Risk (`final_risk_judge`, board-level) | synthesises the other nine per leg into one include/exclude call, and one board-level publish/no-publish recommendation | decides nothing new on its own |

## What the board does NOT do

It does not re-price anything, does not touch `model_survival`, and does not decide
DIRECTION. Its only powers are: veto a leg, apply a point penalty to the reported
confidence (`confidence_penalty` — recorded, never silently absorbed), and flag
correlation risk across the whole candidate list. `engine/combine.py`'s optimizer then
searches only over what the board approved.

## Auditability

Every verdict is a structured record: `{judge, verdict, reason_code, note,
confidence_penalty}`. `tools/daily_combine.py` attaches the full verdict list to every
chosen leg (`leg["referee"]["verdicts"]`) and every vetoed candidate
(`combine.json`'s `vetoed[].all_verdicts`), rendered in full on the "Hakem Kurulu" screen
(`referee.html`) and in the PDF report — nothing is decided off-page.

## Why rule-based and not an LLM panel

The brief is explicit ("Bu yapı harici LLM kullanmamalıdır") and the cost constraint
reinforces it (section 6: no paid LLM calls at runtime). A second reason, specific to this
codebase: every past bug this product actually shipped (the basketball sign error, the
table tennis extrapolation, the tennis-generic HOME_ELO mismatch fixed this session) was
caught by a **named, reproducible, testable check** — a rating-vs-sample-size rule, a
held-out calibration gate, a unit test. An LLM panel would not obviously have caught any of
these faster or more reliably than the deterministic checks that did, and it would have
added a failure mode (inconsistent judgement between runs) that a pure function does not
have.
