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

LADDERS (each rung strictly safer than the one above, same directional view)
  football, side      1 / 2            -> double chance (1X, X2) -> +1, +2, +3 handicap
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
    """Safest-last ladder for 'home wins' or 'away wins'.

    Each rung wins in strictly more states of the world than the one before it: the
    outright result, then result-or-draw, then result-or-lose-by-less-than-N.
    """
    want_win = "1" if side == "home" else "2"
    want_dc = DC_HOME_OR_DRAW if side == "home" else DC_DRAW_OR_AWAY
    ladder = []

    for r in rows:
        g, _ = _group_line(r)
        if g == FOOTBALL_1X2 and _sel(r) == want_win:
            ladder.append((0, r, f"{side} win"))

    for r in rows:
        g, _ = _group_line(r)
        if g == FOOTBALL_DOUBLE_CHANCE and _sel(r) == f"T{want_dc}":
            ladder.append((1, r, f"{side} or draw (does not lose)"))

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


def build(rows, sport_id, direction):
    """All rungs for a direction, most aggressive first.

    `direction` is one of: home, away, over, under.
    """
    if sport_id == 1:
        if direction in ("home", "away"):
            return _rungs_football_side(rows, direction)
        if direction in ("over", "under"):
            return _rungs_total(rows, FOOTBALL_TOTAL, direction)
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
