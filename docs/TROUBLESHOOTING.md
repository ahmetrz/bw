# TROUBLESHOOTING.md

Concrete symptoms, from this session's own debugging, plus the mechanical failure modes
built into the pipeline on purpose.

## "combine.json says no combine, but I expected one"

Read `combine.json`'s `why` field first — it is written for exactly this question. Then:

- `gate_excluded[].reasons` — every candidate that never reached the referee board, and
  why (wrong sport, below 80, started, no odds, data quality blocked).
- `vetoed[].vetoes` — every candidate a judge killed, and which judge, and why
  (`docs/REFEREE_BOARD.md`).
- `borderline[]` — candidates that passed the referee board but the optimizer left out
  because including them would have dropped `combined_probability` below
  `config.MIN_COMBINE_COMBINED_PROBABILITY` (0.15). This is not a bug — see
  `docs/COUPON_OPTIMIZATION.md`.

If `scanned_count` itself is 0 or very low: `combine.json` has no dedicated coverage
section of its own (the scanner's `daily_report.json` used to carry one; it was deleted
with the scanner, `docs/DECISIONS/0007`). Instead, check `tools/daily_combine.py`'s own
run output — it prints `candidate picks: N (skipped: {...})`, where the `skipped` dict
(from `engine/pick.for_fixtures()`) breaks down exactly why a fixture produced no pick:
`no_model` (the sport/team pair isn't in the trained store), `unmodelled_sport` (not
football or tennis, or the sport failed calibration), `no_confident_rung` (a model priced
it but nothing cleared the odds/survival gates) — each further broken down by sport and,
for `no_model`, by league. football/tennis simply may not have had many recognizable
fixtures on that day's card.

## "Tennis never produces picks" — RESOLVED, kept for reference

This described a real, then-current bug: through most of one session, `data/models/4.json`
carried an empty `calibration` table and `model_generic.usable()` correctly refused to
price tennis at all — not a crash, the calibration gate doing exactly its job on a test
window dominated by players the training data didn't cover. The fix (switching the
calibration split from row-count-proportional to date-proportional,
`pmc-2026-08-06-tennis-split`) was filed as a governance proposal, **reviewed and approved
by the operator, and implemented the same session** — tennis now clears calibration at a
0.023 held-out gap and produces picks normally. Full before/after numbers, including a
disclosed side effect on basketball's own calibration, are in `docs/TENNIS_MODELS.md`
(`Status: IMPLEMENTED_AND_VERIFIED`). If tennis ever stops producing picks again, that is a
NEW symptom — start from `docs/TENNIS_MODELS.md`'s diagnostic method, not from the
assumption that this same bug has recurred, and do not "fix" a future occurrence by
lowering `MIN_APPEARANCES` or the calibration threshold — that defeats the gate hard rule 8
exists for.

## "The combine.yml / results.yml commit step failed" or "conflicted with the live watcher"

Expected occasionally — three automated jobs write to this branch (`combine.yml`,
`results.yml`, `watch-live.yml`, plus anyone pushing platform changes by hand). All three
already retry with `git pull --rebase` + reset-and-reapply-MINE-files up to 3-4 times
(`docs/GITHUB_ACTIONS.md`). If it still fails after all retries, the next scheduled run
recovers automatically for everything EXCEPT that day's `data/combine_log.jsonl` row, which
cannot be reconstructed after the fact (by design — see `docs/SELF_LEARNING.md` on why a
record has to be written at selection time or not at all).

## "I pushed by hand and hit a merge conflict on data/models/*.json or data/results/*.jsonl"

This happened during this session's own final push (the live watcher had moved `main`
forward while the work was in progress) and is worth documenting exactly:

1. These files are rewritten WHOLE on every write (`results_store.save()` sorts and
   rewrites, `build_generic_model.py` writes a fresh model) — a line-based git merge on
   them is unreliable even when it appears to succeed.
2. Resolve by taking the REMOTE'S version (`git checkout --theirs <file>`) for any sport
   you did not deliberately modify data for.
3. If you DID deliberately modify one (e.g. a source backfill, like this session's tennis
   `surface` field), re-run the transformation that produced your change AGAINST the
   now-merged data, rather than hand-editing the JSON. This is exactly what this session
   did: `git checkout --theirs data/results/4.jsonl data/models/4.json`, then
   `python3 tools/collect_results.py --source tml --restate` and
   `python3 tools/build_generic_model.py --sport 4` again, then verified the result
   directly before committing. Idempotent operations are the reconciliation mechanism for
   these files — never a manual JSON merge.

## "make_platform_pages.py / make_pdf_report.py crashes on an empty combine.json"

It shouldn't — every `render_*` function in `tools/make_platform_pages.py` and
`tools/make_pdf_report.py` handles `c is None` and `leg_count == 0` explicitly
(`tests/test_combine_platform.py::TestPlatformPages::test_empty_states_render_without_crashing`).
If it does crash, that's a regression — check the traceback names the exact `render_*`
function and file an issue against that function specifically, since each one owns its own
empty-state branch.

## "PDF generation fails with a font error"

`tools/make_pdf_report.py` loads `assets/fonts/DejaVuSans.ttf` /
`DejaVuSans-Bold.ttf` by a path relative to the repo root
(`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`). If this repo is ever
vendored/copied without the `assets/` directory, PDF generation breaks — the fonts are
tracked in git specifically so this cannot happen from a normal clone. Confirm with
`ls assets/fonts/`.

## "Turkish characters look wrong in the PDF"

Should not happen — this was tested explicitly this session
(`tests/test_combine_platform.py::TestPdfReport::test_turkish_characters_render_via_the_vendored_font`).
If it does, check `tools/make_pdf_report._styles()` — every `ParagraphStyle` must use
`fontName="DejaVu"` or `"DejaVu-Bold"`, never `"Helvetica"` (reportlab's default, which
uses WinAnsi encoding and is missing ğ/ı/ş).

## "check_source_health.py reports a source as unavailable that I know works"

Read `docs/DATA_SOURCES.md`'s note on hard rule 10 first: a source is qualified on its
BODY, not its status code — `tools/check_source_health.py._check()` requires both a 200
AND a specific body marker string per source (e.g. football-data.co.uk must contain
`"Div,Date"`). If the source changed its response shape, the marker in
`tools/check_source_health.py`'s `SOURCES` tuple needs updating — this is the intended
failure mode (fail loud on a schema change) rather than a bug to route around.

## "A GitHub Actions step failed but the run is green overall"

By design for every new step added this session — each is `|| echo "<Turkish message>"`,
matching the pre-existing steps' own convention (`docs/GITHUB_ACTIONS.md`). A credential or
one data source being down must never fail a run that otherwise worked (brief's own
instruction, section 4). Check the step's own log line for the echoed reason.
