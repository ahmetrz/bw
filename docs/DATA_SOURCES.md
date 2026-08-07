# DATA_SOURCES.md — the source catalogue

Every source this platform reads from, or considered and rejected, with the fields
section 7 of the platform brief asks for. This file is the single place that answers
"where does this number come from and can I trust it" — `docs/DATA_LICENSING.md` covers
the legal side, `docs/BETWINNER_PROVIDER.md` covers the odds book specifically.

Two generations of research sit underneath this file: the 2026-07-25 sweep recorded in
`research/*.json` (per-sport catalogues, verified live at the time) and the "live watcher
is now the default" pivot recorded in `CLAUDE.md` (2026-08-06), which replaced most
per-sport result archives with one universal source — Betwinner's own live feed. Both are
folded in here rather than re-researched, because re-running the same checks would just
reproduce them at a cost, and CLAUDE.md's own rule (hard rule 10) is to read the body, not
assume a check is stale until there's a reason to think so. Where a status is inherited
rather than freshly checked, the "checked" column says which date it is inherited from.

**Scope note:** this platform's active scope is fixed at football and tennis
(`config.COMBINE_SPORTS = {1, 4}`, `docs/DECISIONS/0007-retire-the-scanner-single-product.md`
— the multi-sport scanner that used to sit alongside this platform is retired). The odds,
football and tennis sections immediately below are current and in active use. Sources
catalogued for every other sport are kept further down as historical record rather than
deleted — real, verified research with standalone value if scope ever widens again — not
because they are still read by anything today.

## Status legend
- **PRODUCTION** — a working adapter reads this today, code path named.
- **RECOMMENDED / NEW** — verified reachable and legal to use, no adapter yet; this session
  adds one where the vertical slice needs it (tennis), documents the rest as backlog.
- **REFUSED** — checked and rejected (robots.txt, licence, block page, or no coverage).
- **BLOCKED** — reachable in principle, blocked from this environment/IP class specifically.

---

## Odds (both sports)

| Source | URL | Auth | Status | Fields | Update freq | Reliability | Checked |
|---|---|---|---|---|---|---|---|
| Betwinner LineFeed (own feed) | `service-api/LineFeed/...` (`engine/bwfeed.py`) | none (public feed) | PRODUCTION | full market tree, odds, `changedAt` staleness, no stake `limit` | live | High — primary book, decoded and regression-tested | 2026-08-06 |
| Betwinner LiveFeed | `LiveFeed/Get1x2_VZip` | none | PRODUCTION | running score, period clock, both name forms, stable participant ids | live, swept every hour | High — this is the results source now (see below) | 2026-08-06 |
| OddsPapi v4 | `api.oddspapi.io` | API key (query param) | REFUSED for Betwinner specifically | — | — | The `betwinner` slug validates but silently returns 22bet's feed under another book's name (`DATA_CONTRACT.md`, `PROBE_FINDINGS.md`). Kept only as a historical record of why the direct feed is used instead. | 2026-07-25 |

## Football — results/history

| Source | URL | Auth | Status | Coverage | License | Reliability | Checked |
|---|---|---|---|---|---|---|---|
| Betwinner LiveFeed (live watcher) | see above | none | PRODUCTION | every football fixture the book carries, ~130/day observed | Betwinner's own data — not a third-party licence question | High for sports it can watch to completion; football finish is CLOCK-detected (`CLOCK_FINISH`), not status-string-detected, because only 1 of 3 watched matches ever showed "Match finished" literally | 2026-08-06 |
| ClubElo | `api.clubelo.com/{Club}` | none | PRESENT, code path DORMANT (`engine/model_football.py` implements it, but sits behind the same unreachable `MODELLED_SPORTS` branch as the hand-written Elo below — `docs/FOOTBALL_MODELS.md`) | ~60 European leagues, Elo back to 1946 | Free, attribution-friendly, no explicit redistribution ban found | High — daily updates, narrow but deep coverage; near-term fixtures only for its leagues | 2026-07-25 |
| Hand-written football Elo (298,950 results, 39 divisions) | internal, `engine/model_elo.py` | n/a | PRESENT, code path DORMANT (`engine/pick.py`'s `MODELLED_SPORTS` is empty, so the branch that would call it is unreachable — `docs/FOOTBALL_MODELS.md`) | wider than ClubElo, in and out of season | n/a (own fit) | **Uncalibrated against unseen matches** — hard rule 8 keeps it out of production until a held-out gap is measured; the generic model currently out-evidences it (0.010 vs unmeasured) | 2026-08-06 |
| football-data.co.uk | `football-data.co.uk/mmz4281/{YY}{YY}/{div}.csv` | none | PRODUCTION-eligible / RECOMMENDED for deeper football | shots, SoT, corners, fouls, cards, referee, HT/FT, closing odds/AH/O-U 2.5; 22+ divisions, 1993/94– | no explicit restriction found on the site; used widely in public research | High — static CSV, no rate limit observed | 2026-07-25 |
| understat.com | `understat.com/match/{id}` | scraping | RECOMMENDED, not yet wired | xG, shots, SoT, deep completions, PPDA; Big-5 + RFPL, 2014/15– | scraping — no explicit ToS grant; personal/research use only | Medium — league INDEX is Cloudflare-gated from datacenter IPs (i.e. from GitHub Actions), match pages were OK. A GH Actions job would need to reach match pages by id, not crawl the index. | 2026-07-25 |
| ESPN football summary API | `site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary` | none | **REFUSED — robots.txt names our crawler.** `anthropic-ai` is `Disallow: /` on espn.com (hard rule 11). Not used regardless of how useful `officials`/lineups/H2H looked in the 2026-07-25 sweep. | — | — | — | 2026-08-06 (robots re-check per hard rule 11) |
| Open-Meteo | `api.open-meteo.com/v1/forecast` | none | RECOMMENDED, not yet wired | global hourly temp/precip/wind, 16-day forecast | Free, CC-BY-attribution-friendly | High, <10k req/day | 2026-07-25 |
| Wikidata SPARQL | `query.wikidata.org/sparql` | none (UA required) | RECOMMENDED, not yet wired | stadium coordinates → travel_km for weather joins | CC0 | High, fair-use rate limit | 2026-07-25 |
| fbref.com | — | — | BLOCKED | richest free football stat set | — | 403 from datacenter IPs (GitHub Actions), with or without a browser UA. Would need residential egress this project does not have. | 2026-07-25 |
| Sofascore | — | — | BLOCKED | — | — | 403 with and without browser headers | 2026-07-25 |
| api-football.com | — | — | UNVERIFIED | — | — | endpoint live, free-tier limits unconfirmed (pricing page itself 403'd) | 2026-07-25 |
| No free source found | — | — | GAP | throw-ins, pitch dimensions/surface, structured injuries/suspensions | — | Do not fabricate these — features that need them are simply omitted, never estimated. | 2026-07-25 |

## Tennis — results/history

| Source | URL | Auth | Status | Coverage | License | Reliability | Checked |
|---|---|---|---|---|---|---|---|
| Betwinner LiveFeed (live watcher) | see above | none | PRODUCTION | every tennis fixture the book carries live, ~of the ~1,000/day total sweep | own data | Sets are a RACE format (best-of-3 and best-of-5 coexist same day), so finish detection is score-vs-format, watched and confirmed, not clock-based like football | 2026-08-06 |
| TML-Database (Tennismylife) | `raw.githubusercontent.com/Tennismylife/TML-Database` | none | PRODUCTION (`tools/collect_results.py`, feeds `engine/model_generic.py` for sport_id 4) | ATP tour-level 1968–2026; ace, df, svpt, 1stIn/Won, 2ndWon, bpSaved/Faced, minutes, height, rank, indoor flag | **"no redistribution/commercial use"** — fine for this single-user, non-commercial tool; would block any future commercialisation without a fresh licence | Medium — stale on GitHub (2026 file stopped 2026-01-17 as of the 07-25 check); ATP tour-level only, no WTA, no Challenger/ITF | 2026-07-25 |
| **tennis-data.co.uk** | `tennis-data.co.uk/alldata.php` (per-season ATP/WTA CSV) | none | **RECOMMENDED / NEW — added this session** (`engine/tennis_data_co_uk.py` collector) | ATP 2000–, WTA 2007–; **Surface**, Court (indoor/outdoor), Round, **Best-of**, per-set games, RET/walkover flag, WRank/LRank, **closing bookmaker odds** (B365/Pinnacle/Betfair, read for calibration reference only, never for direction — hard rule 6) | No explicit redistribution restriction stated on the site; long-standing free public dataset widely used in academic/personal tennis modelling | High — static CSV per season/tour, no rate limit observed, no auth | 2026-08-06 (this session) |
| Jeff Sackmann Match Charting Project | `raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject` | none | RECOMMENDED, not yet wired | point-level serve/return/rally splits per set, 1960–2026 | **CC BY-NC-SA — non-commercial only** | High reachability, but a volunteer SAMPLE (184 matches in 2026 at last check), not full-tour coverage — good for validating serve/return effect sizes, not for per-fixture lookup | 2026-07-25 |
| Sackmann tennis_atp / tennis_wta | `raw.githubusercontent.com/JeffSackmann/tennis_atp` | none | BLOCKED from this environment specifically | full ATP results 1968–present incl. aces/DF/breakpoints | CC BY-NC-SA (same author) | 404 in this session's egress while the sibling `tennis_MatchChartingProject` repo on the same host returns 200 — a per-repo block, not a real 404. Worth a retest from a plain GitHub Actions runner (no proxy) before assuming it stays blocked; TML-Database is used instead in the meantime because it is reachable. | 2026-07-25, retested 2026-08-06 (still 404 via this session's proxy) |
| Tennis Abstract | `tennisabstract.com/reports/atp_elo_ratings.html` | scraping | RECOMMENDED (reports/ only), not yet wired | ATP+WTA Elo incl. surface Elo (hElo/cElo/gElo), court speed ratings per event | scraping, no explicit licence | `/reports/` and `/cgi-bin/` allowed by robots.txt; `/jsmatches/`, `/jsplayers/`, `/jsfrags/` are Disallow — do not use those paths | 2026-07-25 |
| tennisexplorer.com | `tennisexplorer.com/results/` | scraping | RECOMMENDED, not yet wired | ATP/WTA/Challenger/ITF results, per-match serve/return stats, H2H | scraping; robots.txt disallows only `/redirect/`, `/terms-of-use/`, `/contact/` — the most permissive of the scraping candidates | Best coverage of the lower tiers (Challenger/ITF), which TML and tennis-data.co.uk both miss | 2026-07-25 |
| WTA Pulselive API | `api.wtatennis.com/tennis/tournaments/` | none | RECOMMENDED, not yet wired | 18,709 tournaments back to 1960, 36,041 players, surface/level/prizeMoney metadata | unclear — public unauthenticated JSON, no explicit terms found | `/matches` returns `[]` for every ITF-level event tested — real match data starts at WTA 125 | 2026-07-25 |
| ITF (itftennis.com) | — | — | **REFUSED — false 200.** | — | — | HTTP 200 but a 212-byte Incapsula block page, not JSON (hard rule 10: qualify on the body, never the status code). One earlier automated check had marked this VERIFIED on status code alone — corrected. | 2026-07-25 |
| ATP Tour (atptour.com) | — | — | BLOCKED | — | — | 403 Cloudflare on the site and all 4 API paths tried, including the app gateway | 2026-07-25 |
| Ultimate Tennis Statistics | `ultimatetennisstatistics.com` | scraping | REFUSED — stale | Open-Era ATP Elo/stats | — | `season=2025` returns 0 rows, Elo `bestRankDate` stuck at 2024-06-24; historical baseline only, not usable as a live source | 2026-07-25 |
| Sofascore, ATP tennis via api-sports | — | — | BLOCKED | — | — | 403 from this environment; api-sports shows no tennis subdomain at all while all 12 other sports have one | 2026-07-25 |

## Table tennis, basketball, baseball and the other sports — out of scope (historical record)

**Not part of this platform's active scope.** `docs/DECISIONS/0007` fixed scope at football
and tennis (`config.COMBINE_SPORTS = {1, 4}`); every sport in this section left the product
entirely, not merely a ranking within it. Kept rather than deleted because the research
itself — sources checked, verified reachable, or refused on robots.txt/licence/body grounds
— has standalone value if scope ever widens again; nothing in this section is read by the
platform today.

While scope was wider, these were covered by the **generic model**
(`engine/model_generic.py`) fed by two mechanisms:
1. **The live watcher was the default** — `tools/collect_live.py` read Betwinner's own
   `LiveFeed/Get1x2_VZip`, which carries every sport the book runs. This was, at the time,
   how most sports accumulated history at all (table tennis ~490/day, football ~130/day,
   volleyball ~120/day, esports ~60/day, measured over two full runs on 2026-08-06) — the
   highest-volume sports in that measurement, table tennis and volleyball, are exactly the
   ones now outside scope. `tools/collect_live.py`'s watch list (`SPORTS`) is football+tennis
   only today, so none of this is still accumulating; the rows already collected remain in
   `data/results/*.jsonl` as historical record (deleting collected data was a separate,
   larger decision `docs/DECISIONS/0007` did not make).
2. **A handful of pre-existing archives** for sports too thin to wait on the watcher:
   basketball (`api-live.euroleague.net`), baseball (`statsapi.mlb.com`), table tennis
   (Setka API). Table tennis's hand-written model (`engine/model_tt.py`) and its dedicated
   collectors (`tools/collect_tt.py`, `tools/harvest_tt_history.py`,
   `tools/build_tt_model.py`) were **deleted** with the scope narrowing, not merely
   disconnected — unlike football's Elo model, which stays dormant in `engine/pick.py` for a
   one-line re-admission, table tennis left the product entirely so its dedicated code left
   with it.

Sources **checked and refused on robots.txt grounds by our crawler's name** (hard rule 11,
2026-07-26, for sports outside today's scope): NHL (`api-web.nhle.com`, `api.nhle.com`),
OpenDota, Liquipedia, bo3.gg `/api/`, ESPN (all sports, not just football), cbv.com.br, FIVB
(became disallowed after being previously usable — sources can revoke). Checked and found
technically open but useless (hard rule 10, body-not-status-code): `api.openligadb.de` (real
JSON, but its hockey/handball seasons are 2008–2013 and not the competitions on Betwinner's
card), `cev.eu` (a website, not a feed). `api.snooker.org` requires an unregistered
application name (401). `dartsorakel.com` is fully open (`Disallow:` empty) and would be the
best remaining darts candidate if darts ever entered scope.

## Betwinner's own results service — investigated, not usable yet

Documented in full in `CLAUDE.md` under "Where results come from"; summarised here because
it would, if solved, replace the live watcher with one authoritative daily call plus
backfilled history. Route and version are confirmed right
(`service-api/result/web/api/v3/games`, `dateFrom`/`dateTo` in **milliseconds** are real
bound parameters), but a required field is still missing and is neither a header (18 tried)
nor a documented query parameter (42 tried). The `mobile` client path returns HTTP 200 but a
canned `{"count":0}` body regardless of parameters — a decoy, not a working degraded mode
(hard rule 10 again). Not reachable to re-derive from the site itself: `/en/results/` 302s to
`betwinner2.com`, whose `robots.txt` is `Disallow: /`. Left as `RESEARCH_ONLY` — worth
revisiting if the missing field is ever found, but the live watcher is a working substitute
today and nothing depends on this.

## Source health tracking

`docs/DATA_SOURCES.md` (this file) is the human-readable catalogue; the **machine-readable,
self-updating** counterpart is `data/source_health.json`, written by
`tools/check_source_health.py` (new, this session) and rendered on the **Veri Kaynağı
Sağlığı** web panel screen. Each entry carries: source id, last successful access
(timestamp), last check result (ok / degraded / unavailable), consecutive failure count, and
the schema-validation status of the last successful pull (hard rule from section 7 of the
brief: a schema change must flip a source to `degraded`, never fail silently). This file
starts empty on a fresh clone; it is populated by the health-check step described in
`docs/GITHUB_ACTIONS.md` and is intentionally NOT hand-maintained — a stale hand-written
"last checked" date is worse than an honest "never checked by the automated job yet".

## What this means for the two engines built this session

- **Football**: no new adapter was strictly required for the vertical slice — ClubElo +
  the existing Elo model + the live watcher already clear hard rule 8's calibration bar
  (0.010 generic gap per `CLAUDE.md`, improved from 0.012 by the later date-proportional
  calibration-split fix — `docs/TENNIS_MODELS.md`). `football-data.co.uk` is catalogued above as the clear
  next step for a richer factor set (cards, corners, referee) and is left `RECOMMENDED`
  rather than wired in, so as not to grow the football surface area in the same session a
  new sport (tennis) is being added — see `docs/DECISIONS/0002-football-scope-this-session.md`.
- **Tennis**: no new SOURCE was added this session — `tennis-data.co.uk` (the candidate for
  **Surface**, `research/tennis.json`'s own top finding: "Surface Elo is the primary
  predictor; clay/grass specialists diverge 100-200 points from overall") turned out to be
  **unreachable from this sandbox** (TLS handshake failure, catalogued as `BLOCKED` above)
  and, on its own merits, would not have solved the actual blocker anyway — it is main-tour
  only, the same population TML already covers, not the Challenger/ITF tail that turned out
  to be the real gap (`docs/TENNIS_MODELS.md`). What DID ship: TML-Database's own CSV
  already carries a `surface` column that the existing adapter (`tools/collect_results.py`'s
  `tennis()`) was reading but discarding — a one-line fix, not a new source, and it is what
  actually populated `surface` on 29,774 stored rows this session. `tennis-data.co.uk` stays
  catalogued as `RECOMMENDED` (retest from a plain GitHub Actions runner, no proxy) rather
  than claimed as done. See `docs/TENNIS_MODELS.md` and `docs/ROADMAP.md`.
