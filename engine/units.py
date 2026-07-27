"""What each sport's score COUNTS, in one place, because four modules need to agree.

The unit is not a label. It decides which markets a model is allowed to answer, and
getting it wrong is not a rounding error: a table tennis model built from SET scores was
once asked about "total points 76.5" and said 100.00% on a 1.79 shot, because no set total
ever recorded exceeds five. It decides which rungs the ladder may offer, because group 17
counts rallies in volleyball and points in table tennis, not sets. And it decides which
groups the grader can settle.

It used to live inside tools/collect_live.py alongside the finish conditions, where
engine/ code could not reach it — so engine/ladder.py had no way to ask what a sport
counts and simply offered group 17 to everything. The effect was invisible while only
football, tennis and table tennis were modelled, and would have surfaced as a silent zero
the day volleyball's model was admitted: a correct model, a correct card, and no
selections, because every rung it was offered was denominated in something it does not
measure.
"""

# sport id -> what its score counts.
UNIT = {
    1: "goals",     # football
    2: "goals",     # ice hockey
    3: "points",    # basketball
    4: "sets",      # tennis
    5: "runs",      # baseball
    6: "sets",      # volleyball
    8: "goals",     # handball
    10: "sets",     # table tennis
    12: "frames",   # billiards
    13: "points",   # american football
    14: "goals",    # futsal
    16: "sets",     # badminton
    17: "goals",    # water polo
    21: "sets",     # darts — legs or sets, whichever the format notes
    27: "goals",    # field hockey
    29: "sets",     # beach volleyball
    30: "frames",   # snooker
    40: "maps",     # esports
    48: "points",   # lacrosse
    49: "points",   # netball
    60: "points",   # fencing
    66: "runs",     # cricket
    83: "runs",     # softball
    86: "maps",     # counter strike
    97: "maps",     # dota
    109: "maps",    # rocket league
    125: "maps",    # call of duty
    150: "maps",    # starcraft 2
    180: "points",  # kabaddi
    282: "sets",    # padel
    283: "sets",    # pickleball
    298: "maps",    # overwatch
}


def of(sport_id, default="points"):
    """The unit for a sport. Unlisted sports get the default rather than an error —
    a sport we have not classified must still be able to flow through the pipeline and
    be refused for want of a MODEL, not crash for want of a label."""
    return UNIT.get(sport_id, default)
