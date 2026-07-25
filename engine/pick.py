"""Choose one selection per match: model decides the direction, the ladder decides the form.

This is where the operator's rule is enforced end to end.

  1. The MODEL says which way a match leans. Never the price. A short price is a
     probability estimate plus the book's margin plus its exposure, so reading it as a
     probability just hands the book's own opinion back to it.
  2. The LADDER converts that direction into its safest available form — "does not lose"
     rather than "wins", the largest plus-handicap rather than the result, the lowest over
     line rather than the headline one.
  3. The ODDS are consulted at exactly ONE point: the 1.10 gate. Nowhere else.
  4. A confidence floor then throws away anything the model is not actually sure of.
     Without it the ladder would happily return the safest form of a coin flip, which is
     still a coin flip.

The floor is applied to the probability that the LEG SURVIVES, not that it wins. On a
coupon a pushed leg is returned at 1.00 rather than killing the slip, so a whole-number
handicap that refunds on an exact one-goal defeat is genuinely safer than its win
probability suggests, and that difference is exactly what a safety ladder exists to find.
"""
import config
from engine import ladder, model_football

# Directions to consider, in the order they are tried. Sides first: a side view is what
# the ladder can soften most, since double chance and the handicap family both exist.
DIRECTIONS = ("home", "away", "over", "under")


def _survival(row, probs):
    """P(this leg does not lose the coupon) = win + push, or None if unpriceable."""
    got = model_football.rung_probs(row, probs)
    if not got:
        return None
    win, push = got
    return win + push


def candidates(rows, sport_id, probs, min_odds=None, min_survival=None):
    """Every direction's safest qualifying rung, priced by the model.

    Returns a list of dicts with the chosen row, the model's survival probability and the
    reasoning, sorted safest-first. Directions the model cannot price are dropped rather
    than assumed — an unpriced rung must never compete with a priced one.
    """
    if min_odds is None:
        min_odds = getattr(config, "MIN_ODDS", 1.10)
    if min_survival is None:
        min_survival = getattr(config, "MIN_MODEL_SURVIVAL", 0.75)

    out = []
    for direction in DIRECTIONS:
        rungs = ladder.build(rows, sport_id, direction)
        if not rungs:
            continue
        # Walk from safest to riskiest and take the first rung that clears BOTH gates.
        # Safest-first is the whole point: we want the most conservative expression of
        # the view that the book still pays 1.10 for.
        for rung in sorted(rungs, key=lambda x: -x["rank"]):
            row = rung["row"]
            if row["odds"] < min_odds:
                continue
            surv = _survival(row, probs)
            if surv is None or surv < min_survival:
                continue
            picked = dict(row)
            picked["ladder_rung"] = rung["label"]
            picked["ladder_scope"] = rung["scope"]
            picked["model_survival"] = round(surv, 4)
            picked["direction"] = direction
            picked["ladder_available"] = len(rungs)
            out.append(picked)
            break
    out.sort(key=lambda r: -r["model_survival"])
    return out


def best(rows, sport_id, probs, min_odds=None, min_survival=None):
    """The single safest qualifying selection for this match, or None.

    None is a real answer and the common one. A match where the model has no confident
    view, or where every safe form prices below the gate, contributes nothing — padding
    the slip with the least-bad option available would defeat the entire exercise.
    """
    c = candidates(rows, sport_id, probs, min_odds, min_survival)
    return c[0] if c else None


def for_fixtures(rows, index, min_odds=None, min_survival=None, min_name_score=0.82):
    """Run the whole selection over a scan's worth of rows, one pick per match.

    `rows` should be UNFILTERED normalized rows, not the scored top-N: the ladder needs
    alternative lines, and every plus-handicap and every non-headline total is an alt line.
    """
    from engine import model_football as mf

    by_match = {}
    for r in rows:
        if r.get("sub_game"):
            # Full-match probabilities do not describe a half or a corners market. Pricing
            # one with the other produced edges above +1.0 before it was caught.
            continue
        by_match.setdefault(r.get("match_id", r["fixture_id"]), []).append(r)

    picks, skipped = [], {"no_model": 0, "no_confident_rung": 0}
    for match_id, match_rows in by_match.items():
        sample = match_rows[0]
        if sample.get("sport_id") != 1:      # ClubElo is football only
            skipped["no_model"] += 1
            continue
        probs, name_score = mf.lookup(index, sample.get("p1"), sample.get("p2"),
                                      cutoff=min_name_score)
        if not probs or name_score < min_name_score:
            skipped["no_model"] += 1
            continue
        chosen = best(match_rows, sample["sport_id"], probs, min_odds, min_survival)
        if not chosen:
            skipped["no_confident_rung"] += 1
            continue
        chosen["name_match"] = round(name_score, 3)
        picks.append(chosen)

    picks.sort(key=lambda r: -r["model_survival"])
    return picks, skipped
