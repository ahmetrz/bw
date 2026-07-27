"""How much to put on each selection — a risk rule, deliberately not an edge rule.

    plan(picks, unit_pct=0.5, cap=20) -> (picks with .stake, summary)

WHY THIS IS FLAT AND NOT KELLY. Kelly and every other proportional rule sizes a bet by
its EDGE: how much better the true probability is than the price. This product does not
claim an edge — it ranks within one book and says so in the first paragraph of its own
documentation — so there is no edge term to put in the formula. Feeding the model's
probability into Kelly anyway would silently convert "the model is 86% sure" into "the
model is 86% sure AND the book is wrong about it", which is a different and much larger
claim, and it would size the bets on that claim without ever making it out loud.

So the rule is the one that is honest given what is actually known: EVERY SELECTION GETS
THE SAME STAKE. That distributes risk across the list instead of concentrating it, and it
is the only sizing that requires no belief about the price at all.

WHAT THE CAP IS FOR. The list is as long as the card allows — 29 selections one day, 51
the next — and flat staking turns that into a daily exposure that swings by a factor of
two for reasons that have nothing to do with the operator's appetite for risk. The cap
fixes the day's exposure: the top `cap` selections by score are the plan, and the rest
stay on the page marked as outside it. They are NOT deleted, because the operator is
allowed to disagree with a cap they set; they are just not counted in the day's risk.

Two numbers, and both belong to the operator rather than to the model:
  * `unit_pct`  one unit as a percentage of the bankroll
  * `cap`       the most units to have running in one day

WHAT IT REPORTS. The break-even hit rate — the hit rate at which flat staking on this
list returns exactly the stake — is the honest headline, because it is arithmetic on the
book's own prices and asserts nothing. It is reported next to the REALISED hit rate from
the scorecard, never next to the model's claimed confidence: realised is measured, and
the model's confidence is the thing under test. Putting the model's number beside the
break-even one would be a value claim wearing a risk rule's clothes.
"""

# Provisional. These belong to the operator, and until they are confirmed the report says
# so on its face rather than presenting them as a recommendation.
UNIT_PCT = 0.5          # one unit = 0.5% of bankroll
DAILY_CAP_UNITS = 20    # at most 20 units running in one day = 10% of bankroll


def break_even_rate(odds):
    """The hit rate at which flat stakes on these prices return the stake, or None.

    Exact when a win is no more likely on a short price than on a long one within the
    list — which is the assumption, stated rather than buried. With every selection
    staked equally, n bets return (wins × mean odds), so break-even is 1 / mean odds.
    """
    prices = [float(o) for o in odds if o and float(o) > 1.0]
    if not prices:
        return None
    return len(prices) / sum(prices)


def plan(picks, unit_pct=UNIT_PCT, cap=DAILY_CAP_UNITS):
    """Attach a stake to every selection and describe the day's exposure.

    Mutates each pick with `stake` (units, 0 when outside the plan) and `in_plan`.
    Returns the summary dict; the caller decides where to show it.
    """
    ordered = sorted(picks, key=lambda p: p.get("id") or 10 ** 6)
    placed = []
    for i, p in enumerate(ordered):
        inside = cap is None or i < cap
        p["in_plan"] = bool(inside)
        p["stake"] = 1.0 if inside else 0.0
        if inside:
            placed.append(p)

    units = float(len(placed))
    risk_pct = units * unit_pct
    # If every selection in the plan wins. Not a forecast — the other end of the range the
    # day can land in, printed so the risk figure is not the only number with a magnitude.
    win_units = sum(max(0.0, float(p.get("odds") or 0) - 1.0) for p in placed)
    be = break_even_rate([p.get("odds") for p in placed])

    # WHAT ONE POINT OF HIT RATE IS WORTH, in percent of bankroll. This is the number the
    # day actually turns on and it is invisible in the other four: a list of short prices
    # sits close to its own break-even, so the difference between a good day and a bad one
    # is a few points of accuracy rather than the spread between 10% and 2%. Losing every
    # bet is not a scenario, it is an arithmetic bound; being two points under break-even
    # is Tuesday.
    per_point = (units * unit_pct / be / 100.0) if be else None

    return {
        "unit_pct": unit_pct,
        "cap": cap,
        "placed": len(placed),
        "left_out": len(ordered) - len(placed),
        "units": units,
        "risk_pct": round(risk_pct, 2),
        "if_all_win_pct": round(win_units * unit_pct, 2),
        "break_even_rate": be,
        "per_point_pct": round(per_point, 3) if per_point else None,
        "provisional": (unit_pct == UNIT_PCT and cap == DAILY_CAP_UNITS),
    }
