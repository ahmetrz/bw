# BETWINNER_PROVIDER.md

## The brief asks for an abstract provider interface — this codebase already has one

Section 5 of the platform brief asks for odds access to sit behind a protocol like:

```python
class OddsProvider(Protocol):
    def list_events(self, window: TimeWindow) -> list[Event]: ...
    def get_markets(self, event_id: str) -> list[Market]: ...
    def get_odds_snapshot(self, event_id: str) -> OddsSnapshot: ...
```

so a second bookmaker could be added without rewriting the core. This already exists and
predates the combine platform. Its original proof was having TWO independent
implementations behind the same downstream contract, while the now-retired multi-sport
scanner (`docs/DECISIONS/0007`) was still live:

- **`engine/bwfeed.normalize(data)`** — Betwinner's own `GetGameZip`/`LineFeed` shape →
  the row schema. Still the only production source today.
- **`engine/parser.py`** — OddsPapi's aggregator shape → the SAME row schema. Deleted with
  the scanner (`docs/DECISIONS/0007`); OddsPapi was never a source this platform's own
  pipeline read odds from (`docs/DATA_SOURCES.md` records it REFUSED for Betwinner's own
  slug specifically). Kept here as the historical proof that the row shape genuinely
  decouples a source from everything downstream, not as a currently-existing second
  implementation.

Both produced rows carrying the same fields (`fixture_id`, `p1`/`p2`, `market_key`,
`odds`, `selection`, …), and every downstream module (`engine/ladder.py`,
`engine/pick.py`, `engine/combine.py`) is written against that row shape,
never against either source's raw payload. That IS the Protocol the brief asks for — as a
converged **data shape** rather than a formal `typing.Protocol` class, because Python's
structural typing makes the class declaration optional for what actually matters (can a new
source's `normalize()`-equivalent function be dropped in and have everything downstream
keep working) — and a `Protocol` class with no second real implementation under test would
be exactly the "gereksiz mikroservis mimarisi" the brief separately warns against.

## `list_events` / `get_markets` / `get_odds_snapshot`, mapped to what exists

| Brief's method | This codebase's equivalent |
|---|---|
| `list_events(window)` | `tools/fetch_window.py`'s fixture enumeration (`fixtures()`), already windowed and pre-filtered (excluded sports, non-head-to-head) at the enumeration stage |
| `get_markets(event_id)` | `tools/fetch_window.py`'s `game()` → `GetGameZip`, decoded by `engine/bwfeed.normalize()` |
| `get_odds_snapshot(event_id)` | the `odds` field on each normalized row — Betwinner's feed has no separate snapshot call; odds are embedded in the market payload itself |

## Method priority actually followed (brief section 5's ordered list)

1. **Official, documented, permitted open access** — not available; Betwinner publishes no
   public developer API.
2. **Public data requiring no login** — **this is what is used.** `engine/bwfeed.py` reads
   the same `LineFeed`/`GetGameZip` endpoints the public betwinner.com site itself calls,
   unauthenticated, no session, no login (`PROBE_FINDINGS.md`).
3. **Automated web access compliant with law/ToS** — the fetch pattern (`tools/fetch_window.py`)
   is rate-limited, checkpointed, budget-bounded, and identifies itself with a descriptive
   User-Agent (`bw-scanner/1.0`) — see `docs/SECURITY.md` for the full posture.
4. **User-supplied CSV/JSON/HTML export** — `tools/daily_combine.py --input <file>` already
   accepts ANY locally-saved file in the same raw feed shape, which is the manual-import
   fallback (`docs/MANUAL_DATA_IMPORT.md`).
5. **User session** — not used, not needed; method 2 already works.

## What is explicitly refused, regardless of how useful it would be

CAPTCHA/anti-bot bypass, credential-wall circumvention, private/undocumented endpoints
beyond what the public site itself calls, request rates that would look like abuse
(`fetch_window.py`'s budget/checkpoint machinery exists partly for this). None of these are
theoretical constraints — they are the brief's explicit hard prohibitions in section 5,
repeated here because `engine/coupon.py`'s slip-minting call is the one place in this
codebase that talks to an authenticated-adjacent Betwinner endpoint (`SaveCoupon`), and it
still never logs in, never holds a session, and never places a bet — it only asks the
book's own public "share a slip" feature for a loadable code, the same feature exposed on
the site itself with no login required.

## Adding a second bookmaker

Would mean: (1) a new `normalize()`-equivalent producing the same row shape, (2) a new
book-selection mechanism to extend — `config.py` carries no `BOOK` constant at all today
(single-book mode is built into the pipeline directly, not chosen from a config value;
`docs/DECISIONS/0007` dropped the scanner's own `config.BOOK`/multi-book scaffolding along
with the scanner itself, since nothing in the surviving product read it), so this would be
new plumbing, not a flag flip, (3) nothing in `engine/ladder.py`, `pick.py`, `combine.py`,
`referee.py` or `confidence.py` would need to change, because none of them read anything
book-specific — this is the concrete payoff of the existing row-shape abstraction.
