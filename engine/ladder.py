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

Two-outcome sports have no draw to lose to, so their result market IS the safe base and
may sit at the top of a side ladder: basketball, tennis, table tennis, and ice hockey's
two-way moneyline.

LADDERS (each rung strictly safer than the one above, same directional view)
  football, side       double chance (1X, X2) -> +1, +2, +3 handicap  [NO outright win]
  football, over       over 2.5 -> over 1.5 -> over 0.5
  football, under      under 2.5 -> under 3.5 -> under 4.5
  tennis, side         match winner -> +1.5 set handicap ("wins a set")
  table tennis, side   match winner -> +1.5 -> +2.5 set handicap
  basketball, side     moneyline -> + handicap, out to the largest line offered
  ice hockey, side     two-way moneyline -> + handicap
  any sport, over      the lowest line offered
  any sport, under     the highest line offered

WHERE THE GROUP IDS COME FROM
Every id below was read off a real Betwinner payload and confirmed against the prices on
that same fixture, because the feed publishes numeric group ids with no names and a
wrong guess would attach a ladder to the wrong market. The set-handicap groups were the
subtle ones. On a WTA best-of-3 match, group 109 quoted +1.5 at 1.49 against a 2.196
match price and -1.5 at 3.48: in a best-of-3 a +1.5 set handicap loses only to an 0-2
defeat, which is precisely "wins at least one set". Table tennis group 7099 behaves the
same way over best-of-5, where +2.5 is the "wins a set" rung and +1.5 is "wins two".
Group 2 is NOT a set handicap in either sport — its lines track games and points, which
the totals on the same fixture confirm.

SETTLEMENT SCOPE IS PART OF A RUNG
Ice hockey publishes a three-way regulation result (group 1) and a two-way moneyline
that includes overtime and the shootout (group 101) on the same game. They are different
bets, and a ladder that walked from one to the other would change what the bet means
while claiming to hold the view fixed. Every rung therefore carries its scope, and the
hockey handicap rungs are marked unknown rather than assumed, because the 1xBet family
commonly settles those on regulation and we have not read Betwinner's own terms.

Laddering needs ALTERNATIVE lines: "over 1.5" is an alt line when the main total is 2.5,
and so is every plus-handicap. So the ladder is built over the unfiltered row set, not
the main-line-only scan.
"""
import config

FOOTBALL = 1
ICE_HOCKEY = 2
BASKETBALL = 3
TENNIS = 4
TABLE_TENNIS = 10

# --- market groups, confirmed from real payloads ---
G_1X2 = 1                 # three-way result; ice hockey settles this on regulation
G_MONEYLINE_2WAY = 101    # two-way result; ice hockey includes OT and the shootout
G_DOUBLE_CHANCE = 8
G_HANDICAP = 2
G_ASIAN_HANDICAP = 2854
G_TOTAL = 17
G_SET_HANDICAP_TENNIS = 109
G_SET_HANDICAP_TT = 7099

# --- outcome ids within those groups ---
O_DC_HOME_OR_DRAW = 4     # 1X
O_DC_DRAW_OR_AWAY = 6     # X2
O_ML2 = {"home": 401, "away": 402}
O_WIN_2WAY = {"home": 1, "away": 3}       # group 1 in a sport with no draw
O_HANDICAP = {"home": 7, "away": 8}
O_ASIAN_HANDICAP = {"home": 3829, "away": 3830}
O_SET_HANDICAP_TENNIS = {"home": 732, "away": 733}
O_SET_HANDICAP_TT = {"home": 5749, "away": 5750}
O_OVER, O_UNDER = 9, 10

# Sports whose result market has no draw, so the result IS the safe base and may sit at
# the top of a side ladder. Football is absent by construction.
TWO_OUTCOME_SPORTS = {
    ICE_HOCKEY: "ice_hockey",   # via the two-way moneyline, NOT the 60-minute three-way
    BASKETBALL: "basketball",
    TENNIS: "tennis",
    TABLE_TENNIS: "table_tennis",
}


def _group_line(row):
    try:
        g, line = str(row["market_key"][1]).split("|", 1)
        return int(g), (None if line in ("None", "", "*") else float(line))
    except (KeyError, ValueError, TypeError):
        return None, None


def _rung(rank, row, label, scope):
    return {"rank": rank, "row": row, "label": label, "scope": scope}


def _plus_handicaps(rows, side, groups, scope):
    """Plus-handicap rungs: our side may lose by up to |line| and the bet still stands.

    A bigger handicap wins in strictly more states, so rank rises with the line. Only
    positive handicaps qualify — a negative one is a HARDER bet than the result, which is
    the opposite of what a safety ladder is for.

    The line stored on the market key is the line as the HOME side sees it, because that
    is what pairs the two halves of a handicap into one market. So the away side's own
    handicap is its negation: away +2 is carried as a home line of -2. Reading the stored
    line directly for the away side selects the mirror bet, and it prices like one — on
    an NHL game it offered "away +2" at 4.20 against an away moneyline of 2.04, a rung
    supposedly safer than the result at more than twice the price.
    """
    out = []
    for r in rows:
        g, line = _group_line(r)
        if g not in groups or line is None:
            continue
        wanted = (O_HANDICAP if g == G_HANDICAP else O_ASIAN_HANDICAP)[side]
        if r.get("outcome_id") != wanted:
            continue
        own = line if side == "home" else -line
        if own <= 0:
            continue
        # Rank IS the handicap, so handicaps and double chance sit on one scale — see
        # _rungs_football_side.
        out.append(_rung(own, r,
                         f"{side} +{own:g} (does not lose by {own:g})", scope))
    return out


def _rungs_football_side(rows, side):
    """Safest-last ladder for a directional view on the football result.

    Starts at double chance. The outright win is deliberately absent: football has three
    outcomes, so backing the result loses to the draw as well as to defeat, and the
    operator's rule is not to take it. Each rung then wins in strictly more states than
    the one above — result-or-draw, then result-or-lose-by-less-than-N.

    Double chance is ranked as a +0.5 handicap because that is exactly what it is: "home
    or draw" wins in precisely the states where home +0.5 wins. Putting both on the same
    goal scale is what keeps the ordering honest — an Asian +0.25 refunds only half the
    stake on a draw where double chance pays in full, so +0.25 is the RISKIER rung even
    though its number is larger than nothing. Ranking double chance as a separate tier
    above the handicaps had it selecting +0.25 in preference to "does not lose".
    """
    want = O_DC_HOME_OR_DRAW if side == "home" else O_DC_DRAW_OR_AWAY
    ladder = [
        _rung(0.5, r, f"{side} does not lose", "regulation")
        for r in rows
        if _group_line(r)[0] == G_DOUBLE_CHANCE and r.get("outcome_id") == want
    ]
    ladder += _plus_handicaps(rows, side, {G_HANDICAP, G_ASIAN_HANDICAP}, "regulation")
    return sorted(ladder, key=lambda t: t["rank"])


def _rungs_set_sport_side(rows, side, sport):
    """Tennis and table tennis: match winner, then the set handicap.

    In a best-of-3 the +1.5 set handicap loses only to an 0-2 defeat, so it IS the "wins
    a set" bet. In a best-of-5 that rung is +2.5 and +1.5 means "wins at least two", so
    both are offered in line order and the gate decides which survives.
    """
    group, outcomes = ((G_SET_HANDICAP_TENNIS, O_SET_HANDICAP_TENNIS)
                       if sport == TENNIS
                       else (G_SET_HANDICAP_TT, O_SET_HANDICAP_TT))
    ladder = [
        _rung(0.0, r, f"{side} wins the match", "match")
        for r in rows
        if _group_line(r)[0] == G_1X2 and r.get("outcome_id") == O_WIN_2WAY[side]
    ]
    for r in rows:
        g, line = _group_line(r)
        if g != group or line is None or line <= 0:
            continue
        if r.get("outcome_id") != outcomes[side]:
            continue
        ladder.append(_rung(1.0 + line, r, f"{side} +{line:g} sets", "match"))
    return sorted(ladder, key=lambda t: t["rank"])


def _rungs_two_way_side(rows, side, scope, handicap_scope):
    """Basketball and ice hockey: the two-way moneyline, then plus handicaps.

    The moneyline is group 101 in both sports. In ice hockey that matters twice over:
    group 1 is a THREE-way regulation market on the same game, and treating it as the
    result here would both misread the price and change what the bet settles on.
    """
    ladder = [
        _rung(0.0, r, f"{side} wins", scope)
        for r in rows
        if _group_line(r)[0] == G_MONEYLINE_2WAY and r.get("outcome_id") == O_ML2[side]
    ]
    ladder += _plus_handicaps(rows, side, {G_HANDICAP, G_ASIAN_HANDICAP}, handicap_scope)
    return sorted(ladder, key=lambda t: t["rank"])


def _rungs_total(rows, direction, scope, group=G_TOTAL):
    """Totals ladder. Over gets safer as the line falls; under as it rises."""
    want = O_OVER if direction == "over" else O_UNDER
    out = []
    for r in rows:
        g, line = _group_line(r)
        if g != group or line is None or r.get("outcome_id") != want:
            continue
        # Most aggressive first: the highest line for an over, the lowest for an under.
        rank = -line if direction == "over" else line
        out.append(_rung(rank, r, f"{direction} {line:g}", scope))
    return sorted(out, key=lambda t: t["rank"])


# Settlement scope of the result market and of the handicaps, per sport. Anything marked
# unknown is stated as unknown to the user rather than assumed — see engine/settlement.py.
_TOTALS_SCOPE = {
    FOOTBALL: "regulation",
    BASKETBALL: "includes_ot",
    ICE_HOCKEY: "unknown",
    TENNIS: "match",
    TABLE_TENNIS: "match",
}


def build(rows, sport_id, direction):
    """All rungs for a direction, most aggressive first.

    `direction` is one of: home, away, over, under — where home/away mean participant 1
    and participant 2, which is what the feed's O1/O2 carry in the individual sports too.
    An empty list means this sport and direction has no ladder wired, and callers must
    treat that as "no selection", never as licence to fall back to whatever market
    happens to be there.
    """
    if direction in ("over", "under"):
        scope = _TOTALS_SCOPE.get(sport_id)
        return _rungs_total(rows, direction, scope) if scope else []

    if direction not in ("home", "away"):
        return []

    if sport_id == FOOTBALL:
        return _rungs_football_side(rows, direction)
    if sport_id in (TENNIS, TABLE_TENNIS):
        return _rungs_set_sport_side(rows, direction, sport_id)
    if sport_id == BASKETBALL:
        # Full-game basketball markets include overtime across the 1xBet family, but the
        # label has not been read on Betwinner itself, so settlement.py still flags it.
        return _rungs_two_way_side(rows, direction, "includes_ot", "includes_ot")
    if sport_id == ICE_HOCKEY:
        # The moneyline includes OT and the shootout. The handicaps frequently do not on
        # this platform, so they are marked unknown rather than folded into the same scope.
        return _rungs_two_way_side(rows, direction, "includes_ot", "unknown")
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
    qualifying = [x for x in ladder if x["row"]["odds"] >= min_odds]
    if not qualifying:
        return None, f"every rung prices below {min_odds:.2f}"
    # Safest rung that still clears the gate = the last qualifying one, since the ladder
    # is ordered aggressive-first.
    best = qualifying[-1]
    row = dict(best["row"])
    row["ladder_rung"] = best["label"]
    row["ladder_scope"] = best["scope"]
    row["ladder_depth"] = len(qualifying) - 1
    row["ladder_available"] = len(ladder)
    return row, best["label"]
