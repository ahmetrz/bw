"""Betwinner's own line feed -> the same normalized rows as engine/parser.py.

Source: https://betwinner.com/service-api/LineFeed/GetGameZip?id=<CI>&partner=<id>
The book publishes this itself; no API key. It is the 1xBet-platform format, so the
shape below is reverse-engineered from real pulls, not from vendor documentation.

Why this exists at all: OddsPapi never labels its payload `betwinner` — it returns the
same prices keyed `22bet` (measured identical across 12 fixtures, see PROBE_FINDINGS.md).
Reading Betwinner directly removes the labelling ambiguity and carries roughly twice the
markets (298 priced selections vs 147 on one sampled fixture).

Shape:
    Value.CI            stable platform game id — the SAME id OddsPapi reports as
                        bookmakerFixtureId, which is what let the two be compared
    Value.O1 / O2       team NAMES (OddsPapi only gives numeric participant ids)
    Value.S             kick-off, unix seconds
    Value.LE            league name
    Value.GE[]          market groups
        .G              group id  -> market type, see GROUP_TYPES
        .E[][]          selections
            .T          outcome type id
            .C          DECIMAL odds
            .P          line value (totals/handicap); absent on 1X2-style markets
            .CE == 1    the book's own MAIN LINE marker for that group
"""
from datetime import datetime, timezone

# Group id -> market type. Derived by inspecting real payloads: which groups carry a
# line parameter, how many outcomes they have, and how they line up against OddsPapi's
# own market labels for the same fixture. Anything unlisted stays "other" rather than
# being guessed at.
GROUP_TYPES = {
    1: "moneyline",      # 1X2, T = 1 / 2 / 3 — three-way, so only where a draw exists
    101: "moneyline2way",  # two-way result, T = 401 / 402
    8: "doubleChance",   # T = 4 (1X) / 5 (12) / 6 (X2)
    2: "spreads",        # handicap, T = 7 / 8
    2854: "spreads",     # asian handicap, T = 3829 / 3830
    17: "totals",        # match total, T = 9 / 10
    99: "totals",        # asian total, T = 3827 / 3828
    8427: "totals",
    8429: "totals",
    15: "teamTotal",     # team 1 total, T = 11 / 12
    62: "teamTotal",     # team 2 total, T = 13 / 14
    109: "setHandicap",  # tennis, T = 732 / 733
    7099: "setHandicap",  # table tennis, T = 5749 / 5750
    182: "totalSets",    # tennis AND volleyball, T = 971 / 972
    2604: "totalSets",   # table tennis, T = 3150 / 3151
    876: "totalFrames",  # snooker, T = 1850 / 1851
    2436: "totalMaps",   # esports, T = 2824 / 2825
    2438: "mapHandicap",  # esports, T = 2826 / 2827
    136: "correctScore",  # P encodes the scoreline itself, see OUTCOME_ENUM_GROUPS
}

# Volleyball publishes its set handicap and total sets on the SAME groups as tennis (109
# and 182), which is why it needed no new entry here. Snooker instead reuses the ordinary
# handicap group 2 with the line counted in FRAMES, so the group alone does not say what
# a line means — engine/model_generic keys on the sport's declared unit for that reason.

# A two-way result market and a three-way 1X2 are deliberately different types. Ice
# hockey publishes BOTH on the same game — G=1 settles on regulation and can draw, G=101
# includes overtime and the shootout and cannot — and they are not the same product, so
# their holds must not be normalized against one another. Measured on one NHL game: the
# 1X2 and the two-way carried the same 3.1% hold, but the two-way's is spread over two
# outcomes rather than three, which is exactly the kind of difference per-type
# normalization exists to respect.

# Outcome labels only where the meaning is established. Everything else gets a
# structural label so the table never implies a reading that was not verified.
OUTCOME_LABELS = {
    1: "1", 2: "X", 3: "2",                    # 1X2
    4: "1X", 5: "12", 6: "X2",                 # double chance
    401: "ML1", 402: "ML2",                    # two-way result (hockey: incl. OT)
    7: "H1", 8: "H2",                          # handicap sides
    9: "over", 10: "under",                    # match total
    11: "T1 over", 12: "T1 under",             # team 1 total
    13: "T2 over", 14: "T2 under",             # team 2 total
    3827: "over", 3828: "under",
    3829: "H1", 3830: "H2",
    732: "SH1", 733: "SH2",                    # tennis set handicap
    5749: "SH1", 5750: "SH2",                  # table tennis set handicap
    971: "sets over", 972: "sets under",       # tennis and volleyball total sets
    3150: "sets over", 3151: "sets under",     # table tennis total sets
    1850: "frames over", 1851: "frames under",  # snooker total frames
    2824: "maps over", 2825: "maps under",     # esports total maps
    2826: "MH1", 2827: "MH2",                  # esports map handicap
}

# Handicap groups publish the two sides of ONE market at OPPOSITE signed lines: home -1.5
# is quoted against away +1.5. Keying a market on the raw P therefore split every
# handicap into two single-sided "markets" and the hold became meaningless — on the
# football sample the per-market implied sums ran 0.230 to 1.961 instead of clustering
# just above 1. Basketball was worse: every handicap was a lone selection, so all of them
# were dropped for want of a second side. Re-keying on the line as the HOME side sees it
# pairs them correctly: 218 football markets, every one with exactly two selections and a
# hold between 5.2% and 10.6%.
HANDICAP_HOME_SIDE = {2: 7, 2854: 3829}

# Groups where P enumerates an OUTCOME rather than naming a line. Correct score prices
# one selection per scoreline (P = 2.001 means 2:1), so the whole group is a single
# market; keying per P made each scoreline its own one-sided market.
OUTCOME_ENUM_GROUPS = {136}

# How many times a group's selections cover the outcome space. Double chance covers it
# TWICE — 1X, 12 and X2 each contain two of the three results — so its implied
# probabilities sum to about 2, not about 1. Read as a hold that is 100%+, which is how
# every double-chance market in the sample was being scored, and then dropped by
# MAX_OVERROUND. That silently removed the safest rung of the football ladder from the
# scan: measured median sum was 2.154, i.e. a perfectly ordinary 7.7% hold.
MARKET_COVERAGE = {8: 2}


# The feed carries template entries whose participants are the literal strings "Home"
# and "Away" — not real fixtures. They price a full ladder at an unusually low hold, so
# left in they sweep the top of the ranking (observed: the entire top 24). Suppressed at
# parse time; a placeholder has no business reaching the scorer.
PLACEHOLDER_PARTICIPANTS = {("home", "away")}


def _is_placeholder(gm) -> bool:
    return (
        (str(gm.get("O1") or "").strip().lower(), str(gm.get("O2") or "").strip().lower())
        in PLACEHOLDER_PARTICIPANTS
    )


def _is_outright(gm) -> bool:
    """True when the entry has no second participant, so it is not a head-to-head.

    The feed uses an empty O2 for everything that is not two named sides meeting: outright
    winners ("Shanghai Masters. 2026. Winner"), season and election questions ("USA. Senate
    Elections. 2026. Majority"), novelty bundles that appear even inside football ("Sunday
    Enhanced Specials"), and multi-runner races, where the field is the opponent.

    These are dropped because the product's core machinery assumes an opponent. The
    parlay's one-selection-per-match rule has nothing to bind on, and the safety ladder
    cannot run at all — there is no two-outcome side market to walk down from, which is
    also why the animal-racing research found every race carrying a single "win" market
    and nothing else.

    They are also the long-dated bets, and the start timestamp does NOT reveal that. The
    2026 Senate questions are stamped 5 to 16 days out because that is when the line was
    scheduled, not when the seat is decided. A horizon filter on the start time would sail
    straight past them; the missing opponent is what actually identifies them.
    """
    return not str(gm.get("O2") or "").strip()


def is_bwfeed(data) -> bool:
    """True when this looks like a list of Betwinner GetGameZip Value objects."""
    return (
        isinstance(data, list)
        and bool(data)
        and isinstance(data[0], dict)
        and "GE" in data[0]
        and "CI" in data[0]
    )


def _start_iso(unix_seconds):
    if not unix_seconds:
        return None
    try:
        return datetime.fromtimestamp(int(unix_seconds), timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _label(t, p):
    base = OUTCOME_LABELS.get(t, f"T{t}")
    return f"{base} {p}" if p is not None else base


def books_in(data) -> set:
    """Mirrors parser.books_in. A direct pull is Betwinner by construction — it came
    from betwinner.com — so there is no other book it could be reporting."""
    return {"betwinner"} if is_bwfeed(data) else set()


def normalize(data, book="betwinner"):
    """One row per selection, matching engine/parser.py's schema so score.py and
    report.py work unchanged.

    A "market" for overround purposes is one group AT ONE LINE: market_key carries
    "<G>|<P>". Pooling every line of a totals ladder into one market would sum a dozen
    overlapping selections and produce a meaningless hold.
    """
    rows = []
    for gm in data:
        if _is_placeholder(gm) or _is_outright(gm):
            continue
        ci = gm.get("CI")
        start = _start_iso(gm.get("S"))
        # Sub-games (halves, "First To Happen", corners…) arrive as their own game ids
        # carrying the parent's team names, which makes them dangerous in two ways: a
        # full-match model would price a half as if it were the whole game, and a
        # one-selection-per-match rule would count a match and its halves as three
        # separate fixtures.
        #
        # CMG is the marker: null on a real fixture, the parent's id on a sub-game. TG
        # alone is not enough — halves carry an empty TG and name themselves in PN.
        parent = gm.get("CMG")
        is_sub = parent is not None
        tag = (gm.get("PN") or gm.get("TG") or "").strip()
        for grp in gm.get("GE") or []:
            g = grp.get("G")
            mtype = GROUP_TYPES.get(g, "other")
            sels = [
                e
                for sub in (grp.get("E") or [])
                for e in (sub if isinstance(sub, list) else [sub])
                if isinstance(e, dict) and e.get("C")
            ]
            # Does this group use a line parameter at all? If not (1X2, double chance)
            # every selection is a main line by definition.
            lined = any(e.get("P") is not None for e in sels)
            home_t = HANDICAP_HOME_SIDE.get(g)
            coverage = MARKET_COVERAGE.get(g, 1)
            for e in sels:
                price = e.get("C")
                if not price or price <= 1.0:
                    continue
                p = e.get("P")
                t = e.get("T")
                main = True if not lined else (e.get("CE") == 1)
                # The line that identifies the market this selection belongs to.
                if g in OUTCOME_ENUM_GROUPS:
                    line_key = "*"
                elif home_t is not None and p is not None:
                    hl = float(p if t == home_t else -p)
                    line_key = 0.0 if hl == 0 else hl   # keep -0.0 from forking the key
                else:
                    line_key = p
                rows.append({
                    "fixture_id": ci,
                    "p1": gm.get("O1"),
                    "p2": gm.get("O2"),
                    # The book's own participant ids, present on every fixture it lists.
                    # A model that has seen these teams under the same ids can resolve the
                    # fixture EXACTLY, without a name match — which is the one step in
                    # this pipeline that can silently resolve to the wrong team.
                    "p1_id": gm.get("O1I"),
                    "p2_id": gm.get("O2I"),
                    "start": start,
                    # Needed to build the deep link back into Betwinner. The numeric
                    # form /en/line/<sport>/<champ>/<game> resolves; the slug form
                    # would mean guessing a competition slug we do not have.
                    "sport_id": gm.get("SI"),
                    "champ_id": gm.get("LI"),
                    "league": gm.get("LE") or gm.get("L"),
                    "sub_game": is_sub,
                    # The real-world match this row belongs to. Anything that must not
                    # double-count a fixture — the parlay's one-per-match rule, the
                    # per-fixture cap — has to group on THIS, not on fixture_id.
                    "match_id": parent if is_sub else ci,
                    # group + line, so each line is scored as its own market
                    "market_key": (ci, f"{g}|{line_key}"),
                    "market_type": mtype,
                    # How many times this market's selections cover the outcome space.
                    # score.py divides the implied sum by it before calling it a hold.
                    "market_coverage": coverage,
                    # The raw outcome type id. The ladder matches on this rather than on
                    # the display label, so relabelling a market cannot silently detach
                    # a ladder rung from the market it is supposed to select.
                    "outcome_id": t,
                    "is_alt": lined and not main,
                    "main_line": main,
                    "selection": (
                        f"[{tag}] {_label(t, p)}" if tag else _label(t, p)
                    ),
                    "odds": float(price),
                    "implied": 1.0 / float(price),
                    # The feed only publishes selections that are open, so anything
                    # returned is live. There is no separate suspended flag to read.
                    "active": True,
                    "market_active": True,
                    # Betwinner does not publish a stake limit here. Do not invent one.
                    "limit": None,
                    # No per-selection timestamp exists in this feed. The pull time is
                    # the only freshness signal, so staleness cannot be measured
                    # per-selection the way the OddsPapi payload allowed.
                    "changed_at": None,
                })
    return rows
