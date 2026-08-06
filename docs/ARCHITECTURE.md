# ARCHITECTURE.md

## Two products, one engine

```
                    ┌─────────────────────────────────────────────┐
                    │         Betwinner's own LineFeed/LiveFeed     │
                    └───────────────────────┬───────────────────────┘
                                             │
                                    engine/bwfeed.py
                              (normalize -> book-agnostic rows)
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │                                                    │
            engine/score.py                                    engine/pick.py
       (within-book composite score,                    (model direction -> ladder ->
        SUPPRESS rules, diversity cap)                    1.10 gate -> confidence floor)
                    │                                                    │
                    ▼                                                    ▼
         ┌──────────────────────┐                        engine/rating.py (0-100 score)
         │   SCAN PATH           │                                       │
         │   scan.py, report.json│              ┌────────────────────────┴─────────────────────┐
         │   top-N singles       │              │                                                  │
         └──────────────────────┘      DAILY PICKS PATH                              COMBINE PLATFORM PATH
                                     tools/daily_report.py                          tools/daily_combine.py
                                     picks.html, Telegram                        (this session — see below)
```

The scan path (`scan.py`) and the daily-picks path (`tools/daily_report.py`) are the
pre-existing, live product described in full in `CLAUDE.md`. This document does not
re-describe them — it describes what this session added and exactly where it attaches.

## The combine platform, added this session

```
tools/daily_combine.py           entrypoint: its own fetch, own 07:00 Istanbul cron
                                  (combine.yml, docs/DECISIONS/0006), but reuses
                                  daily_report.load_models() for the model layer — same
                                  Elo/generic/ClubElo loading code as the daily-picks
                                  path, restricts to football+tennis, calls
                                  pick.for_fixtures() with those SAME models
        │
        ├─ engine/confidence.py  wraps rating.score() (UNCHANGED) into the full
        │                        ConfidencePrediction contract: EV, implied prob, factors
        │                        up/down, risks, model version — reporting only, never a
        │                        second scoring path (hard rule 6 extended, tested)
        │
        ├─ engine/dataquality.py reason-coded 0-100 data quality score per pick, reusing
        │                        rating.py's own evidence signals (name_match, sample size)
        │                        decomposed by reason rather than recomputed differently
        │
        ├─ engine/combine.py     eligible() [80-pt floor, sport scope, not-started, odds]
        │       │                -> engine/referee.review_all() [10 judges, any veto kills
        │       │                   a leg] -> optimize() [beam search, multi-objective]
        │       │                -> a leg_count>=0 report; empty is a normal outcome
        │       │
        │       └─ engine/referee.py   10 deterministic judge functions + 2 board-level
        │                              judges (correlation, final risk) — NO external LLM
        │
        ├─ engine/coupon.py      UNCHANGED — mints the slip code from combine.py's chosen
        │                        legs exactly as it already does for the daily-picks path
        │
        ├─ combine.json          written; tools/make_platform_pages.py renders it into
        │                        14 screens (tools/webshell.py: shared shell/CSS/escaping,
        │                        deliberately separate from the old pages' own escaping)
        │
        ├─ tools/make_pdf_report.py   combine.json -> combine_report.pdf (reportlab +
        │                             vendored DejaVu font, assets/fonts/ — see below)
        │
        └─ data/combine_log.jsonl     one row per day, append-only selection fields,
                                       settlement filled in later by tools/grade_combine.py
                                       (reuses tools/grade_predictions.py's lookup tables)

engine/governance.py             ProposedModelChange records (data/proposed_changes.jsonl,
                                  never auto-applied) + model-version archiving
                                  (data/models/history/<sport>/, called from
                                  tools/build_generic_model.py before every refit)

engine/track_record.py           reads data/predictions.jsonl: Brier score, log loss,
                                  per-sport calibration, per-market gradeability — feeds
                                  both engine/referee.py's context and lab.html/calibration.html
```

## Why a beam search, not brute force or a simple greedy fill

`engine/combine.py`'s docstring covers this in full; summary: brute force over a card's
worth of eligible legs is 2^n, a single greedy fill cannot trade a marginal leg against the
combined-probability cost of adding it, and the objective is deliberately non-linear
(log-scaled odds utility, sqrt-scaled count utility) so integer programming's linear-
objective sweet spot does not fit either. Verified against brute force on small candidate
sets during this session (matches exactly, see the session's own testing, not repeated in
this repo as a permanent test since it is O(2^n)).

## Data flow ownership — what writes what, and when

| File | Written by | Cadence | Notes |
|---|---|---|---|
| `combine.json` | `tools/daily_combine.py` | daily (`combine.yml`, own 07:00 Istanbul cron + own fetch — `docs/DECISIONS/0006`) | rebuilt fresh each run |
| `combine_report.pdf` | `tools/make_pdf_report.py` | daily | from `combine.json` |
| `data/combine_log.jsonl` | `tools/daily_combine.py` (append) / `tools/grade_combine.py` (settlement field only) | daily append, hourly settle | selection fields never rewritten once logged |
| `data/proposed_changes.jsonl` | `engine/governance.propose()` | ad hoc, analyst-run | never auto-applied; status changes only via `governance.review()` |
| `data/models/history/<sport>/*.json` | `engine/governance.archive_model_version()` | daily, before each refit | last 30 kept per sport |
| `data/source_health.json` | `tools/check_source_health.py` | daily | probes catalogued sources, qualifies on body not status code |
| `combine.html` … 13 more screens | `tools/make_platform_pages.py` | daily + hourly (results.yml) | never hand-edited |

## What was deliberately NOT built as new abstraction

- **No Pydantic entity classes.** The brief's section 23 entity list (Event, Market,
  Selection, DataQualityAssessment, …) already exists as precisely-shaped **dicts** flowing
  through `engine/bwfeed.py` -> `engine/pick.py` -> `engine/rating.py` -> `engine/confidence.py`.
  Introducing a parallel typed class hierarchy that nothing in the pipeline would actually
  use would be exactly the "gereksiz mikroservis mimarisi" the brief warns against. This
  document, `docs/CONFIDENCE_SCORING.md` and the test suite ARE the schema — precise,
  enforced by tests, just not a separate class file.
- **No microservices.** Everything is one Python process per pipeline step, invoked
  sequentially from a GitHub Actions job, exactly like the pre-existing scanner.
- **No live settings UI.** `settings.html` is read-only; changes are made by editing
  `config.py` like any other code change, with structural changes routed through
  `engine/governance.py`'s proposal record first.

## Where the old and new pages meet

They don't share a template. `tools/make_picks_page.py` / `make_stats_page.py` /
`make_method_page.py` each escape and render independently (already true before this
session) and are unmodified. `tools/webshell.py` is a **second**, independent shell used
only by the 14 new screens. Cross-linked by relative `<a href>` in the new pages' nav bar;
the old pages do not link forward (`docs/DECISIONS/0001` — minimising risk to a live,
tested page generator was worth more than a two-way nav bar).
