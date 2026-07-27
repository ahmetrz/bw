"""Settle a recorded prediction against a final score.

This is the half of the product that makes every other half falsifiable. Until a pick is
graded it is an opinion; once it is graded the hit rate is a fact, and the day-to-day
question "did the model actually help" becomes answerable rather than rhetorical.

Grading is deliberately EXPLICIT per market rather than clever. Each rung the ladder can
select has its own settlement arithmetic, and getting one of them subtly wrong would
corrupt the very measurement the improvements are steered by — a grader that silently
scores a push as a loss makes whole-number handicaps look worse than they are, and the
next round of "improvements" would then remove the safest rungs in the ladder.

Outcomes:
    win   the leg paid
    push  the stake was returned (the coupon survives; the leg pays 1.00)
    half  a quarter-line split half won, half pushed — returns more than stake, less than a full win
    loss  the leg died
"""

WIN, PUSH, HALF, LOSS = "win", "push", "half", "loss"

# Groups and outcome ids, matching engine/ladder.py and engine/bwfeed.py.
G_1X2, G_DOUBLE_CHANCE, G_HANDICAP, G_ASIAN_HANDICAP, G_TOTAL, G_ML2 = 1, 8, 2, 2854, 17, 101

# HANDICAPS IN A UNIT THAT IS NOT GOALS. The arithmetic is identical — a margin against a
# line — but the group and outcome ids differ per sport, and a group this file does not
# list settles as None, which means the prediction is never graded at all.
#
# That is exactly what happened, and it is why the first real hit rate was empty. The
# safety ladder's favourite table tennis rung is a set handicap on group 7099, table
# tennis was the second most-predicted sport, and every one of those predictions sat
# ungraded for ever while the coverage looked like a data problem. It was not: the results
# were in the store. Nothing could score them.
#   109  tennis AND volleyball set handicap
#   7099 table tennis set handicap
#   2438 esports map handicap
HANDICAP_GROUPS = {
    G_HANDICAP: (7, 8),
    G_ASIAN_HANDICAP: (3829, 3830),
    109: (732, 733),
    7099: (5749, 5750),
    2438: (2826, 2827),
}

# Totals in the same position: group 17 counts goals or points, and these count sets,
# frames or maps. Same arithmetic, different ids.
#   182  total sets, tennis and volleyball      2604 total sets, table tennis
#   876  total frames, snooker                  2436 total maps, esports
TOTAL_GROUPS = {
    G_TOTAL: (9, 10),
    182: (971, 972),
    2604: (3150, 3151),
    876: (1850, 1851),
    2436: (2824, 2825),
}

# Team totals: the line applies to ONE side's score rather than to the pair.
TEAM_TOTAL_GROUPS = {
    15: ("home", 11, 12),
    62: ("away", 13, 14),
}


def _parts(row):
    try:
        group, line = str(row["market_key"][1]).split("|", 1)
        return int(group), line
    except (KeyError, ValueError, TypeError, IndexError):
        return None, None


def _handicap(margin, own_line):
    """Settle one handicap at a line expressed from the backed side's own point of view.

    `margin` is that side's goal difference. A whole line can push; a quarter line splits
    the stake across the two neighbouring half-lines, so half of it can push while the
    other half wins or loses.
    """
    frac = abs(own_line) % 1
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        a = _handicap(margin, own_line - 0.25)
        b = _handicap(margin, own_line + 0.25)
        if a == b:
            return a
        if {a, b} == {WIN, PUSH}:
            return HALF          # half won, half returned
        if {a, b} == {LOSS, PUSH}:
            return LOSS          # half lost, half returned — the coupon leg is dead
        return LOSS
    adj = margin + own_line
    if adj > 0:
        return WIN
    if adj == 0:
        return PUSH
    return LOSS


def settle(row, home_goals, away_goals):
    """Grade one selection against a final score, or None if the market is unsupported.

    None is returned rather than a guess: a market this grader does not understand must
    leave the prediction ungraded, because scoring it wrongly is worse than not scoring it.
    """
    group, line_txt = _parts(row)
    oid = row.get("outcome_id")
    if group is None or home_goals is None or away_goals is None:
        return None

    margin = home_goals - away_goals

    if group == G_1X2:
        if oid == 1:
            return WIN if margin > 0 else LOSS
        if oid == 2:
            return WIN if margin == 0 else LOSS
        if oid == 3:
            return WIN if margin < 0 else LOSS
        return None

    if group == G_ML2:
        # Two-way result. A draw cannot occur in the sports that publish it (it settles
        # after overtime), so a level score means the recorded result is incomplete.
        if margin == 0:
            return None
        if oid == 401:
            return WIN if margin > 0 else LOSS
        if oid == 402:
            return WIN if margin < 0 else LOSS
        return None

    if group == G_DOUBLE_CHANCE:
        if oid == 4:
            return WIN if margin >= 0 else LOSS       # 1X
        if oid == 5:
            return WIN if margin != 0 else LOSS       # 12
        if oid == 6:
            return WIN if margin <= 0 else LOSS       # X2
        return None

    if group in HANDICAP_GROUPS:
        try:
            stored = float(line_txt)
        except (TypeError, ValueError):
            return None
        home_oid, away_oid = HANDICAP_GROUPS[group]
        # market_key holds the line as the HOME side sees it.
        if oid == home_oid:
            return _handicap(margin, stored)
        if oid == away_oid:
            return _handicap(-margin, -stored)
        return None

    if group in TOTAL_GROUPS:
        try:
            ln = float(line_txt)
        except (TypeError, ValueError):
            return None
        over_oid, under_oid = TOTAL_GROUPS[group]
        total = home_goals + away_goals
        if total == ln:
            return PUSH
        if oid == over_oid:
            return WIN if total > ln else LOSS
        if oid == under_oid:
            return WIN if total < ln else LOSS
        return None

    if group in TEAM_TOTAL_GROUPS:
        try:
            ln = float(line_txt)
        except (TypeError, ValueError):
            return None
        side, over_oid, under_oid = TEAM_TOTAL_GROUPS[group]
        scored = home_goals if side == "home" else away_goals
        if scored == ln:
            return PUSH
        if oid == over_oid:
            return WIN if scored > ln else LOSS
        if oid == under_oid:
            return WIN if scored < ln else LOSS
        return None

    return None


def payout(result, odds):
    """What one unit staked on this leg returns. Used for the running P&L."""
    return {
        WIN: odds,
        PUSH: 1.0,
        HALF: 1.0 + (odds - 1.0) / 2.0,
        LOSS: 0.0,
    }.get(result, 1.0)


def summarize(graded):
    """Hit rate and return over a set of graded predictions.

    Pushes are reported separately rather than folded into either column: counting a
    returned stake as a win overstates the model and counting it as a loss understates it.
    """
    if not graded:
        return None
    wins = sum(1 for g in graded if g["result"] == WIN)
    halves = sum(1 for g in graded if g["result"] == HALF)
    pushes = sum(1 for g in graded if g["result"] == PUSH)
    losses = sum(1 for g in graded if g["result"] == LOSS)
    decided = wins + halves + losses
    staked = len(graded)
    returned = sum(payout(g["result"], g["odds"]) for g in graded)
    return {
        "graded": len(graded),
        "win": wins, "half": halves, "push": pushes, "loss": losses,
        "hit_rate": (wins + halves) / decided if decided else None,
        "staked": staked,
        "returned": round(returned, 3),
        "roi_pct": round(100.0 * (returned - staked) / staked, 2) if staked else None,
    }
