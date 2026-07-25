"""Safety laddering: express a directional view in its safest available market form.

THE RULE
Direction comes from the model, never from the price. Once a direction is fixed, walk
that direction's ladder from the most aggressive form to the safest, and take the safest
rung that still prices at or above `config.MIN_ODDS`. Odds are consulted at exactly one
point — that gate — and nowhere else.

Why the direction must not come from the price: a short price is not a high probability.
It is a probability estimate plus the book's margin plus whatever the book's exposure
requires, and reading it as a probability just relaunders the book's own opinion back at
it. Selecting on short prices would build a slip out of the book's margin, not out of
anything we know.

THE OUTRIGHT WIN IS NOT A RUNG IN FOOTBALL
Football resolves three ways, so backing a team to win is backing one of three outcomes
and the draw beats you on its own. The ladder therefore starts at double chance — "does
not lose" — and never offers the outright result. If no rung from double chance down
clears the gate, that direction simply yields nothing for that match; falling back to
the outright win would be picking the riskiest form precisely when the safe forms are
too short, which is backwards.

Two-outcome sports have no draw to lose to, so their moneyline IS the safe base and is
allowed as the top rung: basketball, tennis, and ice hockey's moneyline (which includes
overtime and the shootout, unlike its three-way regulation market).

LADDERS (each rung strictly safer than the one above, same directional view)
  football, side      double chance (1X, X2) -> +1, +2, +3 handicap   [NO outright win]
  football, over      over 2.5         -> over 1.5 -> over 0.5
  football, under     under 2.5        -> under 3.5 -> under 4.5
  tennis, side        match winner     -> +1.5 set handicap ("wins a set")
  basketball, side    moneyline        -> + handicap, largest available
  basketball, over    lowest line
  basketball, under   highest line

Laddering needs ALTERNATIVE lines: "over 1.5" is an alt line when the main total is 2.5,
and so is every plus-handicap. So the ladder is built over the unfiltered row set, not
the main-line-only scan.
"""
import config

# Betwinner market groups, by sport, for the forms a ladder needs to reach.
FOOTBALL_1X2 = 1
FOOTBALL_DOUBLE_CHANCE = 8      # T=4 (1X), T=5 (12), T=6 (X2)
FOOTBALL_HANDICAP = 2           # T=7 home, T=8 away, P = line
FOOTBALL_TOTAL = 17             # T=9 over, T=10 under, P = line

# Double-chance outcome ids on group 8.
DC_HOME_OR_DRAW = 4
DC_HOME_OR_AWAY = 5
DC_DRAW_OR_AWAY = 6


def _group_line(row):
    try:
        g, line = str(row["market_key"][1]).split("|", 1)
        return int(g), (None if line in ("None", "") else float(line))
    except (KeyError, ValueError, TypeError):
        return None, None


def _sel(row):
    return str(row.get("selection") or "")


def _rungs_football_side(rows, side):
    """Safest-last ladder for a directional view on the result.

    Starts at double chance. The outright win is deliberately absent: football has three
    outcomes, so backing the result loses to the draw as well as to defeat, and the
    operator's rule is not to take it. Each rung then wins in strictly more states than
    the one above — result-or-draw, then result-or-lose-by-less-than-N.
    """
    want_dc = DC_HOME_OR_DRAW if side == "home" else DC_DRAW_OR_AWAY
    ladder = []

    for r in rows:
        g, _ = _group_line(r)
        if g == FOOTBALL_DOUBLE_CHANCE and _sel(r) == f"T{want_dc}":
            ladder.append((1, r, f"{side} does not lose"))

    # Plus handicaps: our side may lose by up to |line| and the bet still stands.
    # Bigger handicap = safer, so order ascending by line then reverse at the end.
    hcp_label = "H1" if side == "home" else "H2"
    for r in rows:
        g, line = _group_line(r)
        if g == FOOTBALL_HANDICAP and line is not None and line > 0 and _sel(r).startswith(hcp_label):
            ladder.append((2 + line, r, f"{side} +{line:g} (does not lose by {line:g})"))

    return sorted(ladder, key=lambda t: t[0])


def _rungs_total(rows, group, direction):
    """Totals ladder. Over gets safer as the line falls; under as it rises."""
    out = []
    for r in rows:
        g, line = _group_line(r)
        if g != group or line is None:
            continue
        s = _sel(r)
        if direction == "over" and s.startswith("over"):
            out.append((-line, r, f"over {line:g}"))
        elif direction == "under" and s.startswith("under"):
            out.append((line, r, f"under {line:g}"))
    # Most aggressive first: highest line for over, lowest for under.
    return sorted(out, key=lambda t: t[0])


# Sports whose result market has no draw, so the moneyline is already the safe base and
# may sit at the top of a side ladder. Football is absent by construction; ice hockey is
# here for its moneyline, which includes overtime and the shootout — its three-way
# regulation market does have a draw and must not be treated the same way.
TWO_OUTCOME_SPORTS = {
    2: "ice_hockey",   # moneyline only, NOT the 60-minute three-way
    3: "basketball",
    4: "tennis",
}


def build(rows, sport_id, direction):
    """All rungs for a direction, most aggressive first.

    `direction` is one of: home, away, over, under. An empty list means this sport and
    direction has no ladder wired yet — callers must treat that as "no selection", never
    as licence to fall back to whatever market happens to be there.
    """
    if sport_id == 1:
        if direction in ("home", "away"):
            return _rungs_football_side(rows, direction)
        if direction in ("over", "under"):
            return _rungs_total(rows, FOOTBALL_TOTAL, direction)

    # Tennis ("wins a set"), basketball (+handicap at the largest line, totals at the
    # extreme line) and ice hockey moneyline are specified but not wired: their Betwinner
    # group ids have not been read off a real payload yet, and guessing an id would
    # attach a ladder to the wrong market. The 48h sweep supplies those payloads.
    return []


def safest(rows, sport_id, direction, min_odds=None):
    """The safest rung whose odds clear the gate.

    Returns (row, rung_label) or (None, reason). The gate is the ONLY place odds are
    read; everything above this picked rungs purely on how much they widen the set of
    winning outcomes.
    """
    if min_odds is None:
        min_odds = getattr(config, "MIN_ODDS", 1.10)
    ladder = build(rows, sport_id, direction)
    if not ladder:
        return None, "no ladder for this sport/direction"
    qualifying = [(rank, r, label) for rank, r, label in ladder if r["odds"] >= min_odds]
    if not qualifying:
        return None, f"every rung prices below {min_odds:.2f}"
    # Safest rung that still clears the gate = the last qualifying one, since the ladder
    # is ordered aggressive-first.
    rank, row, label = qualifying[-1]
    row = dict(row)
    row["ladder_rung"] = label
    row["ladder_depth"] = len(qualifying) - 1
    row["ladder_available"] = len(ladder)
    return row, label
