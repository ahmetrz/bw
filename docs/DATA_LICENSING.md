# DATA_LICENSING.md — what we're allowed to do with each source

This platform is built for **one person's personal, non-commercial use** (master brief
§2: "Uygulama yalnızca tek kullanıcı tarafından kullanılacaktır"). That single fact
resolves most of the licensing tension in the sources this project relies on — several of
them are explicitly non-commercial-only, which would be disqualifying for a product sold
or offered to others, and is not disqualifying here. This document exists so that if the
scope ever changes (the tool is shared, hosted for others, or monetised), there is one
place that says which sources would need a fresh licensing pass before that happens.

## The two licence-restricted sources in production

| Source | Licence | What it restricts | Why it's fine today | What would break it |
|---|---|---|---|---|
| **TML-Database** (Tennismylife) | "no redistribution / commercial use" (stated in `research/tennis.json`) | Redistributing the raw data, or using it commercially | Used only as a **fitting input** — raw rows are not exposed to any user, only aggregate statistical outputs (Elo ratings, calibration tables) derived from them, for one person's own decision support | Publishing the raw CSV/JSONL, or charging for access to the tool |
| **Jeff Sackmann Match Charting Project** | CC BY-NC-SA (non-commercial, share-alike) | Commercial use of the data or derivatives; requires attribution + share-alike if redistributed | RECOMMENDED but not yet wired into a production model this session — flagged here so whoever wires it in later inherits the constraint | Same as above, plus: if wired in, any derived dataset redistributed under a different licence would violate share-alike |

Everything else catalogued in `docs/DATA_SOURCES.md` as PRODUCTION or RECOMMENDED is
either unencumbered public data (government/official sports-body statistics, static CSVs
published with no redistribution clause, e.g. `football-data.co.uk`, `tennis-data.co.uk`),
or Betwinner's own feed (not a licensing question — see the ToS note below), or free-tier
public APIs with no field-level usage restriction found (ClubElo, Open-Meteo, Wikidata
SPARQL, WTA Pulselive).

## Scraped sources — legal posture, not just robots.txt

A handful of sources (`understat.com` match pages, `tennisexplorer.com`, `tennisabstract.com`
`/reports/`) are reached by parsing HTML rather than calling a documented API. Hard rule 11
already gates these on **robots.txt naming our crawler** before any fetch — that is a
necessary check, not a sufficient one. None of these sites publish an explicit "scraping is
permitted" grant; the operating assumption here, consistent with the master brief's "hukuka
ve hizmet koşullarına uygun otomatik web erişimi" (§5) requirement, is:
- robots.txt allows the specific path (checked, dated, recorded per source in
  `docs/DATA_SOURCES.md`),
- requests are low-frequency and cached (this platform pulls once a day for football/tennis
  plus the hourly live-result sweep — not a scraping-at-scale operation),
- no CAPTCHA or anti-bot measure is bypassed (master brief §5, hard prohibition — if a
  source ever puts one up, hard rule 10's "qualify on the body" check will surface it as a
  block page and the source gets marked `unavailable`, not worked around),
- output is used for personal statistical modelling, not republished.

This is a defensible reading, not a legal opinion. If this tool is ever shared with anyone
beyond the operator, every scraped source in `docs/DATA_SOURCES.md` needs a fresh look
before that happens — this file is the checklist for that review, not a one-time clearance.

## Betwinner itself

Betwinner's own feed (`engine/bwfeed.py`, `LiveFeed`) is read the same way a browser reads
it — no authentication bypass, no CAPTCHA defeat, no rate that would look like abuse
(`fetch_window.py`'s budget/checkpoint/backoff behaviour exists partly for this reason, not
just for GitHub Actions' own timeout). Automated access to a bookmaker's feed still sits
under that bookmaker's own terms of service, which this project does not have a signed
copy of and cannot evaluate as a legal matter — `PRODUCT_STATUS.md`'s risk register already
flags this ("accounts get limited or closed for less") and that risk is unchanged by this
session's work. The platform **never places a bet or fills a slip automatically** (master
brief §2, §15, hard rule against auto-betting; `engine/coupon.py` produces a **code the
operator types into the book's own UI**, and stays that way) — that line is the one place
this project has drawn a hard boundary against ToS risk it cannot evaluate for itself, and
this session does not move it.

## Jurisdiction

Unchanged from `PRODUCT_STATUS.md`'s existing note: offshore sportsbooks occupy a legally
grey-to-prohibited position in a number of jurisdictions, including, per that document, the
operator's own. That is a **product/personal decision**, not something this session's
engineering work can resolve, and it is repeated here rather than re-litigated.

## What this means for the two new engines this session

- **Tennis**: the one new production data source added this session, `tennis-data.co.uk`
  (see `docs/DATA_SOURCES.md`), carries **no stated redistribution or commercial-use
  restriction** — it is the cleanest-licensed of the three tennis history sources
  catalogued, which is part of why it was chosen as the surface-Elo source over expanding
  reliance on TML/Sackmann.
- **Football**: no new licence-restricted source was added this session (see ADR
  0002) — the existing production sources (ClubElo, football-data.co.uk if wired in later)
  carry no stated restriction either.
