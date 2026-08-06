# MARKET_ONTOLOGY.md

## Where the market vocabulary actually lives

There is one decoded vocabulary, `engine/bwfeed.py`'s `GROUP_TYPES` (Betwinner's numeric
market-group id → a `market_type` string) and `OUTCOME_LABELS` (outcome id → a short token:
`1`/`X`/`2`, `1X`/`12`/`X2`, `over`/`under`, `home`/`away`, …), decoded from real payloads
and extended only when a new group is confirmed against a real pull — never guessed
(`DATA_CONTRACT.md`). Every other module that needs to know what a market means —
`engine/ladder.py`'s rung selection, `engine/grade.py`'s settlement groups,
`engine/model_generic.py`'s `HANDICAP_GROUPS`/`TOTAL_GROUPS`, `engine/tr.py`'s Turkish
labels — reads or re-derives from the SAME group/outcome ids, not a second parallel list.
This session added no new market types; it reuses the existing ontology for the two sports
(football=1, tennis=4) already in it.

## The trap this ontology exists to avoid

**A market-group id is not globally unique in meaning across sports.** Group `2` is a goal
handicap in football but a games handicap in tennis (and is deliberately unmodelled by
`model_generic.py`'s generic path for tennis — see `HANDICAP_GROUPS["sets"]`, which excludes
group 2 entirely). Group `109` is a SET handicap shared by tennis AND volleyball; group
`182` is total sets, also shared. `engine/units.py`'s `UNIT` dict (sport → `"goals"` /
`"sets"` / `"points"` / …) is what disambiguates — a distribution "only answers questions
asked in its own unit," per `engine/model_generic.py`'s own docstring, and this is enforced
by test (`tests/test_regression.py::test_a_distribution_only_answers_questions_in_its_own_unit`).

## Football and tennis markets this platform can actually price today

Both sports go through the SAME model layer (`engine/pick.py`), which prices only what the
underlying model's distribution covers:

| Market family | Football | Tennis |
|---|---|---|
| Match winner / moneyline | yes (via 1X2 + draw handling) | yes (2-way, no draw — `TWO_OUTCOME_SPORTS`) |
| Double chance | yes | n/a (no draw to hedge) |
| Handicap (goals/sets) | yes | yes (SET handicap only — game-level handicap group 2 excluded) |
| Totals (goals/sets) | yes | yes (SET totals only) |
| Correct score, cards, corners, player props, set betting, tie-break yes/no | **not modelled** | **not modelled** |

The right-hand gaps are not a bug list — they are markets `research/football.json` and
`research/tennis.json` catalogue factors for (corners need shot/possession data not yet
wired — `docs/DECISIONS/0005`; tie-break yes/no needs hold-percentage data this session did
not add) that the current models genuinely cannot price honestly yet. `engine/pick.py`
refuses rather than approximates them, per hard rule 1/2.

## Entities (platform brief section 23) — as dicts, not classes

`docs/ARCHITECTURE.md`'s "What was deliberately NOT built" section explains why these are
documented shapes rather than a parallel class hierarchy. The core ones, and where each
lives:

| Entity | Shape lives in | Key fields |
|---|---|---|
| Event / Fixture | `engine/bwfeed.normalize()`'s row | `fixture_id`, `game_id`, `p1`/`p2`, `p1_id`/`p2_id`, `start`, `sport_id`, `league` |
| Market / Selection | same row | `market_key` (`(fixture_id, "group|line")`), `market_type`, `selection`, `odds`, `outcome_id` |
| OddsSnapshot | implicit in the row | `odds`, `staleness_seconds` (bwfeed: always `None` — no per-selection timestamp in this feed) |
| ModelPrediction | `engine/pick.py`'s output | `model_survival`, `model_win`, `model_push`, `direction`, `ladder_rung`, `model_source` |
| DataQualityAssessment | `engine/dataquality.assess()`'s return | `score`, `reasons[]` (reason-coded), `blocks_combine` |
| RefereeDecision | `engine/referee.py`'s `Verdict` shape | `judge`, `verdict`, `reason_code`, `note`, `confidence_penalty` |
| CouponCandidate / FinalCoupon | `engine/combine.build_combine()`'s return | `legs[]`, `combined_odds`, `combined_probability`, `why` |
| Result / Settlement | `data/results/<sport>.jsonl` row / `engine/grade.settle()`'s return | `home_score`, `away_score` / `WIN`\|`LOSS`\|`PUSH`\|`HALF` |
| PerformanceMetric | `engine/track_record.py`'s returns | Brier, log loss, calibration gap |
| ModelVersion | `data/models/history/<sport>/*.json` | archived model snapshot, filename carries date + game count |
| ProposedModelChange | `data/proposed_changes.jsonl` row | see `docs/MODEL_GOVERNANCE.md` |
| PipelineRun | `data/combine_log.jsonl` row (`generated_at`, `config_fingerprint`) + `data/watch_log.jsonl` | rendered on `runs.html` |
| SourceHealthCheck | `data/source_health.json` | `state`, `http_status`, `checked_at` |
