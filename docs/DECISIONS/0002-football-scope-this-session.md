# ADR 0002 — Football gets no new data source this session

**Date:** 2026-08-06
**Status:** Accepted

## Context

The brief asks for a wide football factor set: xG, shots, corners, cards, fouls, referee
tendency, weather, lineups, and more. `research/football.json` (dated 2026-07-25, already
in the repo) has already catalogued verified free sources for nearly all of it —
`football-data.co.uk` (shots/SoT/corners/fouls/cards/referee), `understat.com` (xG, PPDA),
`open-meteo.com` (weather), `wikidata` (stadium coordinates for travel). None of these are
wired into `engine/model_football.py` today; the production football model is Elo-based
(ClubElo + a hand-written 298,950-result Elo, the latter not yet promoted per hard rule 8).

Football already clears the platform's calibration bar today (the generic model measures a
0.012 held-out gap per `CLAUDE.md`), and football is not the sport this session's ADR 0001
identified as the clear gap — tennis is (no surface-awareness at all before this session).

## Decision

This session does not wire a new football data source or rebuild the football model. It:
- Documents the already-researched sources in `docs/DATA_SOURCES.md` as `RECOMMENDED`,
  ready for a future session to wire in without re-researching.
- Extends the football-facing REPORT (confidence factors, data-quality score, referee-board
  review) to work with whatever `model_football.py`/`model_generic.py` already produce for
  football, being explicit in the report about which of the brief's listed football factors
  are actually used (Elo, home/away split) versus not yet available (xG, corners, cards,
  referee, weather, lineups) — see `docs/FOOTBALL_MODELS.md`.
- Leaves `docs/DECISIONS/0005-football-enrichment-backlog.md` as the concrete next step.

## Consequences

- Football's confidence scores this session are honest about being Elo-only; they are not
  inflated by claiming factors that are not actually computed.
- Tennis gets the session's model-building effort, since it is starting from "generic model
  only, no surface-awareness" while football already has two working models and a
  calibration pass.
- A future session can wire `football-data.co.uk` into `model_football.py` (cards/corners/
  referee submodels) using the exact same held-out-calibration discipline this session
  applies to tennis, without needing to re-do the source research.
