# ROADMAP.md — near-term backlog

Every item here traces to something this session concretely found — a measured gap, a
blocked check, a deliberate scope cut recorded in an ADR — not a wishlist item invented
for completeness. Where a fuller writeup already exists, this points to it rather than
repeating it.

## Awaiting an operator decision (engineering is done; a human call is the blocker)

### 1. Tennis calibration split — `pmc-2026-08-06-tennis-split`

Filed in `data/proposed_changes.jsonl`, `status: "proposed"`, rendered on the "Önerilen
Model Değişiklikleri" screen. Full evidence in `docs/TENNIS_MODELS.md`; short version:
`tools/build_generic_model.py`'s calibration split is 80/20 **by row count**, which for
tennis allocates the entire 7,745-row test window to the last **11 days** of a
2015–2026 archive — a population dominated by a recent tennisexplorer/live-watcher
density spike, almost entirely Challenger/ITF/qualifying players the training slice never
saw. Result: 0 of 7,745 test rows have both sides clearing `MIN_APPEARANCES`, the
calibration table comes back empty, and tennis is refused — correctly, per hard rule 8,
not as a bug to route around.

The proposed fix — switch to a date-proportional split — is plausible and specifically
scoped, but `build()` is shared by every sport currently in production (football,
basketball, baseball, table tennis all calibrate through the same function), so changing
it needs a human to weigh "fixes tennis" against "re-validates four other sports'
calibration gaps that already pass." That's exactly what `engine/governance.py`'s
proposal queue exists to gate (`docs/DECISIONS/0004`). Next step: operator reviews the
proposal (`engine/governance.review()`), and if approved, someone re-runs
`build_generic_model.py --all` and confirms all five sports' gaps still clear their
bars before this is merged.

### 2. The 07:00 Istanbul cadence question

The platform brief specifies a 07:00 Europe/Istanbul run; `daily.yml`'s existing,
operator-approved cron (`43 6,7,8 * * *` UTC ≈ 09:43/10:43/11:43 Istanbul) is roughly
2.5–4.5 hours later, and this session did not change it — reusing the existing job
inherited the existing trigger time, and moving an already-approved schedule needs the
same approval gate that set it (CLAUDE.md HITL gate 5), not an edit made in passing.
Full detail in `docs/GITHUB_ACTIONS.md`. Next step: operator decides between an earlier
cron, a second scheduled firing at 07:00 specifically, or accepting the current time —
not an engineering decision to make unilaterally.

## Blocked on a real gap, not just unwired

### 3. Surface-partitioned tennis rating pools

`data/results/4.jsonl` already carries `surface` for every TML-sourced row (backfilled
this session onto 29,661 rows: 17,652 Hard / 8,859 Clay / 3,126 Grass / 14 Carpet / 123
unlabelled — `docs/TENNIS_MODELS.md`), and `research/tennis.json` names surface as the
single strongest tennis predictor (clay/grass specialists diverging 100–200 Elo points
from their overall rating). Splitting rating pools by surface is not implemented, and the
reason is not effort — it's that surface is only known at **training** time. Betwinner's
own card publishes no surface indicator per tennis fixture, and tennisexplorer — the one
source dense enough to cover the recent/lower-tier population the calibration gap above
lives in — doesn't carry it either. A name/tournament-based guess for the live card was
considered and rejected: a silently wrong surface guess is exactly the class of error
hard rule 10 exists to prevent, and unlike an outright refusal it would be very hard to
notice from outside. **Blocked on finding or building an inference-time surface signal
for the live card** — not on any further modelling work with what's already stored.
Fragmenting an already-thin dataset by surface before that exists would also make item
#1's calibration gap strictly harder to close, not easier (`docs/TENNIS_MODELS.md`).

## Catalogued and reachable — no blocker, just not built yet

### 4. Football enrichment: football-data.co.uk cards/corners/referee

`docs/DATA_SOURCES.md` already lists `football-data.co.uk` as
**PRODUCTION-eligible / RECOMMENDED for deeper football** — static CSVs, no auth, no
rate limit observed, 22+ divisions back to 1993/94, and it already carries shots, SoT,
corners, fouls, cards, referee name, and closing odds/AH/O-U 2.5 columns that
`engine/model_football.py` does not read today (it only reads the CSV's score columns,
via `tools/collect_results.py`'s `football` adapter). This session deliberately did not
wire it in — `docs/DECISIONS/0002` records the scope cut in favour of putting the
session's modelling effort into tennis, which had zero working coverage before this
session versus football's two working models. Formally recorded as backlog in
`docs/DECISIONS/0005-football-enrichment-backlog.md`. Next step: a football-specific
enrichment of `engine/model_football.py` using the same held-out-calibration discipline
already applied to the generic model and to tennis — not a new source to research, the
CSV and its columns are already being fetched for the score data alone.

### 5. understat.com, Open-Meteo, Wikidata into football

All three catalogued `RECOMMENDED, not yet wired` in `docs/DATA_SOURCES.md`, none touched
this session (`docs/DECISIONS/0002`):

- **understat.com** — xG, shots, SoT, deep completions, PPDA for Big-5 + RFPL since
  2014/15. Reachability caveat already measured: the league **index** page is
  Cloudflare-gated from datacenter IPs (i.e. from GitHub Actions), but individual match
  pages were reachable in the 2026-07-25 sweep. An adapter would need to reach match
  pages directly by id rather than crawling the index — a real constraint on how the
  adapter has to be written, not a reason it's unreachable.
- **Open-Meteo** — free, no auth, global hourly forecast, generous rate limit. Needs a
  stadium → coordinates join to be usable at all.
- **Wikidata SPARQL** — the join Open-Meteo needs: stadium coordinates, CC0, no auth
  beyond a UA string. Two sources that are only useful together.

Next step for both: build the stadium-coordinate join once (Wikidata), then wire weather
as a factor (Open-Meteo) — genuinely new modelling work, not just a fetch, since neither
factor exists in `model_football.py` today in any form.

## Not on this list on purpose

Anything catalogued `BLOCKED` or `REFUSED` in `docs/DATA_SOURCES.md` (fbref.com,
Sofascore, ATP Tour, ITF's false-200 block page, robots-disallowed sources) stays off
this backlog — those aren't "not done yet," they're checked and closed unless the
underlying block changes. `tennis-data.co.uk` is a partial exception worth naming
precisely: cataloguing work identified it as the best-licensed surface-carrying tennis
source, but this session's attempt to reach it hit a TLS handshake failure specific to
this sandbox's egress (distinct from the TML/GitHub path, which works fine) — no
collector for it exists in `engine/` today. Worth a retest from a plain GitHub Actions
runner (no proxy in front of it) before either building the adapter or writing it off;
even if reachable, `docs/TENNIS_MODELS.md` is explicit that it wouldn't by itself close
item #1's calibration gap, since it's main-tour-only — the same population TML already
covers — while the gap is in the Challenger/ITF/qualifying tail.
