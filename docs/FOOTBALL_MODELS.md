# FOOTBALL_MODELS.md

## Status: `IMPLEMENTED_AND_VERIFIED`, narrower than the brief's factor wishlist

Football (Betwinner `sport_id = 1`) is the one sport in this platform's two-sport scope
that already clears calibration and already produces live picks — nothing about this
session was required to make football usable. This document is honest about which of the
brief's section 9 factor list is actually computed today versus catalogued-but-not-wired
(`docs/DECISIONS/0002` records the decision not to widen football's factor set this
session, in favour of putting the session's model-building effort into tennis, which had
zero working coverage before this session — see `docs/TENNIS_MODELS.md`).

## What actually prices a football fixture

One model prices every football selection today. `engine/pick.py`'s `MODELLED_SPORTS` —
the list of sports with a HAND-WRITTEN model tried before the generic path — is empty, so
`engine/pick.resolve()`'s `sport not in MODELLED_SPORTS` branch is always taken for
football and returns straight from the generic-model lookup; the `if sport == 1:` branch
below it (hand-written Elo, then ClubElo) is unreachable code today, not a live fallback:

1. **Generic model** (`engine/model_generic.py`, sport 1) — counted Elo-plus-margin
   fitted from stored results (`data/results/1.jsonl`, fed by `football-data.co.uk` + the
   live watcher). **This is the only model actually admitted for football**: 0.010
   held-out calibration gap (improved from 0.012 by the date-proportional split fix —
   `docs/TENNIS_MODELS.md`), comfortably inside the 0.03 bar. Per hard rule 8 ("a model is
   wired in on its calibration, not its reach"), this is what `engine/pick.py` uses for
   every football selection today.
2. **Hand-written Elo** (`engine/model_elo.py`) — fitted on 298,950 results across 39
   divisions, own history, works in and out of season, reaches more fixtures than the
   generic model. **Dormant, not a fallback** — hard rule 8 requires held-out calibration
   before a model is trusted, and this one has never been measured against unseen matches,
   so it left `MODELLED_SPORTS` earlier and the branch that would call it is unreachable.
   Kept, not deleted, so re-admitting it is a one-line change if a future comparison ever
   favours it (`docs/DECISIONS/0007`).
3. **ClubElo** (`engine/model_football.py`) — ~60 European leagues, near-term fixtures
   only, Poisson-pair scoreline matrix with a fitted draw correction. Sits behind the same
   now-unreachable `if sport == 1:` branch as the hand-written Elo — present in the code,
   never actually called while `MODELLED_SPORTS` stays empty.

## Factors actually used vs. the brief's list (section 9)

| Factor (brief) | Status | Where |
|---|---|---|
| Elo rating | **used** | `engine/model_generic.py`, `engine/model_elo.py`, `engine/model_football.py` |
| Home/away split | **used** | `HOME_ELO` term in `fit_ratings()` |
| Rest days, fixture congestion | **not modelled** | would need a fixture-schedule join not currently built |
| xG / xGA | **not modelled, source catalogued** | `understat.com`, `docs/DATA_SOURCES.md`, `docs/DECISIONS/0005` |
| Shots, corners, cards, fouls, referee tendency | **not modelled, source catalogued** | `football-data.co.uk` has all of these columns, unused — `docs/DECISIONS/0005` |
| Weather | **not modelled, source catalogued** | `open-meteo.com`, needs a stadium-coordinate join (Wikidata SPARQL, also catalogued, also unwired) |
| Lineups/injuries | **not modelled, no free reliable source found** | `docs/DATA_SOURCES.md`'s football section: "no_free_source: structured_injuries_suspensions" |
| Head-to-head | **deliberately not weighted** | `research/football.json`'s own finding: "weakest item: small n, stale rosters. Near-zero weight" — not wired in on purpose, not an oversight |
| Market odds | **read at exactly one point** | the `MIN_ODDS=1.10` gate — never as a probability input (hard rule 6) |

## What this means for the confidence score on a football pick

`engine/dataquality.py`'s `LINEUP_DATA_UNAVAILABLE` and `SOURCE_CONFLICT` reason codes are
attached to every football (and tennis) selection, always, at `INFO` severity — a standing,
honest disclosure that no lineup/injury source and no second odds source are integrated,
rather than a claim that these were checked and came back clean. `engine/confidence.py`'s
`factors.down` list will name a specific weakness (thin sample, fuzzy name match) when one
exists; it will never claim a strength the model does not actually have (e.g. it will not
say "confirmed starting XI" because nothing confirms one).

## Next step, concretely

`docs/DECISIONS/0005-football-enrichment-backlog.md` records wiring
`football-data.co.uk`'s existing columns (cards, corners, fouls, referee) into a genuine
football-specific enrichment of `engine/model_football.py`, using the exact same held-out
calibration discipline this session applied to tennis. Not started this session — the
research and the source are already there, the modelling work is not.
