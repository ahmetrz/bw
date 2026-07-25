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
    1: "moneyline",      # 1X2, T = 1 / 2 / 3
    2: "spreads",        # handicap, T = 7 / 8
    2854: "spreads",     # asian handicap, T = 3829 / 3830
    17: "totals",        # match total, T = 9 / 10
    99: "totals",        # asian total, T = 3827 / 3828
    8427: "totals",
    8429: "totals",
    15: "teamTotal",     # team 1 total, T = 11 / 12
    62: "teamTotal",     # team 2 total, T = 13 / 14
}

# Outcome labels only where the meaning is established. Everything else gets a
# structural label so the table never implies a reading that was not verified.
OUTCOME_LABELS = {
    1: "1", 2: "X", 3: "2",                    # 1X2
    7: "H1", 8: "H2",                          # handicap sides
    9: "over", 10: "under",                    # match total
    11: "T1 over", 12: "T1 under",             # team 1 total
    13: "T2 over", 14: "T2 under",             # team 2 total
    3827: "over", 3828: "under",
    3829: "H1", 3830: "H2",
}


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
        if _is_placeholder(gm):
            continue
        ci = gm.get("CI")
        start = _start_iso(gm.get("S"))
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
            for e in sels:
                price = e.get("C")
                if not price or price <= 1.0:
                    continue
                p = e.get("P")
                main = True if not lined else (e.get("CE") == 1)
                rows.append({
                    "fixture_id": ci,
                    "p1": gm.get("O1"),
                    "p2": gm.get("O2"),
                    "start": start,
                    # group + line, so each line is scored as its own market
                    "market_key": (ci, f"{g}|{p}"),
                    "market_type": mtype,
                    "is_alt": lined and not main,
                    "main_line": main,
                    "selection": _label(e.get("T"), p),
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
