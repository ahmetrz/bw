"""Score each selection out of 100, from the analysis alone.

THE SCORE IS THE MODEL'S WIN PROBABILITY, discounted when the evidence behind it is thin.

    puan = 100 × ( eşik + (olasılık − eşik) × kanıt )

That is the whole formula, and it is written this way because the first version was not
readable. It scored confidence as a POSITION IN A BAND — how far past the floor a pick sat
— so a selection the model gave 75.8% came out as 28/100. Defensible arithmetic, unusable
number: "28" was read as "the model is 28% sure", which is the opposite of what it meant.

A score has to mean one thing to the person reading it. This one means: the model thinks
this bet wins about this often. 89 is "about 89%". Nothing to translate.

The DISCOUNT is the part that is still ours to judge. Two selections the model both puts
at 90% are not equally well founded — one may rest on an exact team match in a division
fitted from 12,000 results, the other on a fuzzy name match in a division fitted from 400.
So the probability is pulled back toward the entry threshold in proportion to how thin the
evidence is: full evidence keeps the full probability, no evidence collapses it to the
floor, which is the least the selection could have been worth and still be here.

Deliberately built from NOTHING the book tells us. The odds are consulted at exactly one
point in this product — the 1.10 gate — and a score that quietly folded the price back in
would reintroduce the book's opinion through the side door, which is the single rule this
project is most careful about.

Because every selection has already cleared MIN_MODEL_SURVIVAL, the scores necessarily sit
in a narrow band above it. That is not a defect to be spread out cosmetically: the band IS
the product. Stretching it would manufacture apparent differences between a 91% and a 93%
that the model cannot actually support.
"""
import config

# Plain-language bands, so the number can be read at a glance without doing arithmetic.
# Cut at round probabilities rather than at quantiles of the day's list: a fixed meaning
# survives a weak card, whereas quantiles would relabel the same bet every morning.
BANDS = (
    (92.0, "çok güçlü"),
    (88.0, "güçlü"),
    (83.0, "orta"),
    (0.0, "sınırda"),
)


def band(score):
    for cut, label in BANDS:
        if score >= cut:
            return label
    return BANDS[-1][1]


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
    """Points out of 100 plus the two numbers that produced them."""
    if floor is None:
        floor = getattr(config, "MIN_MODEL_SURVIVAL", 0.75)
    prob = pick.get("model_survival")
    eviz = _evidence(pick)
    if prob is None:
        total = 100.0 * floor
    else:
        total = 100.0 * (floor + max(0.0, prob - floor) * eviz)
    return {
        "score": round(total, 1),
        "band": band(total),
        "model_pct": round(100.0 * prob, 1) if prob is not None else None,
        "evidence_pct": round(100.0 * eviz, 1),
        # What the thin evidence cost this selection, in the same units as the score. A
        # discount you cannot see is a discount you cannot argue with.
        "evidence_penalty": round(100.0 * (prob - floor) * (1.0 - eviz), 1)
                            if prob is not None else 0.0,
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
