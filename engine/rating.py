"""Score each selection out of 100, from the analysis alone.

Deliberately built from NOTHING the book tells us. The odds are consulted at exactly one
point in this product — the 1.10 gate — and a score that quietly folded the price back in
would reintroduce the book's opinion through the side door, which is the single rule this
project is most careful about.

So the two components are both ours:

  CONFIDENCE (70) — how sure the model is, measured from the floor upward. A selection
  that only just clears MIN_MODEL_SURVIVAL scores near zero here, not near 70: everything
  offered has already passed the floor, so the interesting question is how far past it a
  pick sits, not that it passed.

  EVIDENCE (30) — how much the model's opinion is worth on THIS fixture. The same 90%
  means less when it rests on a fuzzy name match, a thin division, or a rating-gap bucket
  with few observations behind it. Two picks with identical confidence are not equally
  well founded, and the score should say so.

The breakdown travels with the score so the page can show why a pick rates what it does.
A single opaque number would be worse than no number: it invites trust it has not earned.
"""
import config


def _confidence(survival, floor):
    """0..1 across the band a selection can actually occupy: floor to certainty."""
    if survival is None:
        return 0.0
    head_room = 1.0 - floor
    if head_room <= 0:
        return 1.0
    return max(0.0, min(1.0, (survival - floor) / head_room))


def _evidence(pick):
    """0..1 for how well-supported this fixture's model call is.

    Three things degrade it, each for a concrete reason:
      * a fuzzy name match — the ratings may belong to a neighbouring club or player
      * a thin sample behind the rating bucket (table tennis set distributions)
      * a division fitted on few matches (football)
    """
    parts = []

    # Name matching. An exact match is worth full marks; anything fuzzy is discounted by
    # how fuzzy it was, since a wrong match attaches the wrong team's ratings entirely.
    name = pick.get("name_match")
    if name is not None:
        parts.append(max(0.0, min(1.0, (name - 0.80) / 0.20)))

    # Table tennis: the set distribution is binned, and a bucket with few observations
    # behind it is a weaker claim than one with thousands.
    n = pick.get("model_n")
    if n:
        parts.append(min(1.0, n / 1500.0))

    # Football: a division fitted on more matches gives steadier ratings.
    fitted = pick.get("division_matches")
    if fitted:
        parts.append(min(1.0, fitted / 5000.0))

    if not parts:
        return 0.6      # priced, but nothing to corroborate it with — mid, not full
    return sum(parts) / len(parts)


def score(pick, floor=None):
    """Points out of 100 plus the breakdown that produced them."""
    if floor is None:
        floor = getattr(config, "MIN_MODEL_SURVIVAL", 0.75)
    conf = _confidence(pick.get("model_survival"), floor)
    eviz = _evidence(pick)
    total = 70.0 * conf + 30.0 * eviz
    return {
        "score": round(total, 1),
        "confidence_points": round(70.0 * conf, 1),
        "evidence_points": round(30.0 * eviz, 1),
        "confidence_pct": round(100.0 * conf, 1),
        "evidence_pct": round(100.0 * eviz, 1),
    }


def annotate(picks, floor=None):
    """Attach the score to every pick and number them 1..N, best first.

    The id is assigned AFTER sorting, so #1 is always the best-rated selection of the day
    rather than whichever fixture happened to be parsed first.
    """
    for p in picks:
        p.update(score(p, floor))
    picks.sort(key=lambda p: (-p["score"], -(p.get("model_survival") or 0)))
    for i, p in enumerate(picks, 1):
        p["id"] = i
    return picks
