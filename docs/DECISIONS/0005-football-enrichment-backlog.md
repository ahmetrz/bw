# ADR 0005 — Football enrichment: accepted, backlogged, not this session

**Date:** 2026-08-06
**Status:** Accepted

## Context

`docs/DECISIONS/0002` scoped football out of this session's modelling work: it already
clears the platform's calibration bar (generic model, 0.012 held-out gap), and the
session's effort went to tennis instead, which had zero working surface-awareness before
this session. That ADR promised this document as the concrete record of what was
deferred and why it's a real next step rather than a closed question.

Three sources are already catalogued in `docs/DATA_SOURCES.md`, verified reachable
(with one caveat below) and clear of any redistribution restriction that would block
this project's single-user, non-commercial use (`docs/DATA_LICENSING.md`):

- **football-data.co.uk** — `PRODUCTION-eligible / RECOMMENDED`. Already fetched by
  `tools/collect_results.py`'s `football` adapter for its score columns alone; the same
  CSVs also carry shots, SoT, corners, fouls, cards, and referee name, none of which
  `engine/model_football.py` reads today.
- **understat.com** — `RECOMMENDED, not yet wired`. xG, shots, SoT, deep completions,
  PPDA for the Big-5 leagues + RFPL since 2014/15. The league index page is
  Cloudflare-gated from datacenter IPs; individual match pages were reachable in the
  2026-07-25 sweep, so an adapter needs to address match pages by id rather than crawl
  the index.
- **Open-Meteo + Wikidata SPARQL** — both `RECOMMENDED, not yet wired`. Wikidata supplies
  stadium coordinates; Open-Meteo turns those into a weather factor. Neither is useful
  without the other.

None of the three have an adapter, and `engine/model_football.py` uses none of their
fields today — it prices a fixture from Elo alone (own hand-written fit, ClubElo, or the
generic model's counted Elo-plus-margin; see `docs/FOOTBALL_MODELS.md`).

## Decision

Accept all three as backlog, formally, rather than leaving them as informal notes inside
`docs/DATA_SOURCES.md`:

- Wiring any of them into `engine/model_football.py` is **in scope for a future
  session**, not rejected or deprioritized indefinitely.
- When that session happens, it uses the same held-out-calibration discipline hard rule
  8 already requires and this session already applied to tennis: a factor is admitted on
  a measured, held-out calibration improvement, not on the intuitive appeal of adding
  more inputs. Adding cards/corners/xG/weather to the feature set without re-measuring
  calibration on unseen matches would be exactly the kind of confident-but-wrong model
  hard rule 8 exists to catch.
- No source research is required before that session starts — `docs/DATA_SOURCES.md`
  and this document are the complete starting point. The work that remains is modelling
  and calibration, not discovery.

## Consequences

- Football's confidence reporting stays honest in the meantime: `docs/FOOTBALL_MODELS.md`
  states plainly which brief-listed factors are used (Elo, home/away split) versus
  catalogued-but-not-wired (xG, corners, cards, fouls, referee, weather), and
  `engine/dataquality.py` attaches a standing disclosure to every football selection
  rather than implying these were checked and came back clean.
- This backlog does not block anything currently in production — football already clears
  calibration without these factors, so there is no dependency forcing this work before
  any other item in `docs/ROADMAP.md`.
- The next session to pick this up should re-check robots.txt / reachability for
  understat.com and re-verify football-data.co.uk's CSV shape hasn't changed before
  building against them (hard rules 10 and 11) — the 2026-07-25/2026-08-06 checks in
  `docs/DATA_SOURCES.md` are dated, not permanent clearances.
