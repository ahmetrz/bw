"""Table tennis probabilities from the calibrated Setka model (data/model_tt.json).

WHAT THE CALIBRATION ACTUALLY SAYS, because it changes how this sport should be played:

The match winner is close to unpredictable from ratings. Fitted on 7,726 recent matches,
the logistic scores a log loss of 0.6546 against a coin flip's 0.6931 — real signal, but
thin — and its most confident prediction in the calibration table is 0.722. It would
essentially never clear a 75% confidence floor, and it should not.

The SET HANDICAP is a different story. At a rating gap of 6-10 the underdog loses 0-3 only
8% of the time, so "wins at least one set" lands above 90%. Same match, same ratings, and
a completely different level of certainty — which is exactly what the safety ladder exists
to find, and the clearest evidence so far that the operator's rule is the right one.

So the set distribution is measured, not derived. A per-point model would need serve data
that nobody publishes, and the observed 3-0 / 3-1 / 3-2 split IS the set-handicap market.
"""
import json
import os

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "model_tt.json"
)

G_MATCH_WINNER = 1        # T = 1 / 3
G_SET_HANDICAP = 7099     # T = 5749 / 5750
G_TOTAL_SETS = 2604       # T = 3150 over / 3151 under

_NOISE = frozenset(("jr", "sr", "ii"))


def load(path=MODEL_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _norm(name):
    s = (name or "").lower()
    for ch in ".-'":
        s = s.replace(ch, " ")
    return " ".join(p for p in s.split() if p and p not in _NOISE)


def build_player_index(players):
    """Normalized name -> rating, from engine.setka.ratings()."""
    idx = {}
    for pid, p in (players or {}).items():
        rating = p.get("ratingSc")
        if rating is None:
            continue
        name = _norm(f"{p.get('firstName','')} {p.get('lastName','')}")
        if name:
            # Two players can share a normalized name; an ambiguous name must not resolve
            # to whichever happened to be indexed last.
            idx.setdefault(name, []).append(rating)
    return {n: r[0] for n, r in idx.items() if len(r) == 1}


def _bucket(model, gap):
    """The measured set distribution for this rating gap."""
    dists = model.get("set_distribution") or {}
    best = None
    for key, entry in dists.items():
        lo, hi = (float(x) for x in key.split("-"))
        if lo <= gap < hi:
            return entry
        if best is None or entry.get("n", 0) > best.get("n", 0):
            best = entry
    return best


def lookup(model, index, p1, p2):
    """Probabilities for one fixture, or (None, 0.0) when either player is unrated."""
    if not model or not index:
        return None, 0.0
    r1, r2 = index.get(_norm(p1)), index.get(_norm(p2))
    if r1 is None or r2 is None:
        return None, 0.0

    a = model["logistic"]["a"]
    b = model["logistic"]["b"]
    z = max(-30.0, min(30.0, a + b * (r1 - r2)))
    p1_win = 1.0 / (1.0 + 2.718281828459045 ** (-z))

    entry = _bucket(model, abs(r1 - r2)) or {}
    dist = entry.get("dist") or {}
    # The distribution is stored from the FAVOURITE's point of view, so it is flipped
    # when player 1 is the underdog.
    fav_is_p1 = r1 >= r2
    sets = {}
    for key, prob in dist.items():
        f, d = key.split("-")
        sets[(int(f), int(d)) if fav_is_p1 else (int(d), int(f))] = prob

    return {
        "p1_win": p1_win, "p2_win": 1.0 - p1_win,
        "sets": sets,
        "_rating": (r1, r2),
        "_gap": round(abs(r1 - r2), 1),
        "_n": entry.get("n", 0),
        "_source": "setka",
    }, 1.0


def rung_probs(row, probs):
    """(win, push) for a table tennis selection, or None where it cannot be priced.

    Only the markets the measured distribution genuinely covers are priced. Point totals
    and point handicaps are deliberately absent: they need a per-rally model, and pricing
    them off a set distribution would be inventing precision the data does not contain.
    """
    try:
        group = int(str(row["market_key"][1]).split("|", 1)[0])
        line_txt = str(row["market_key"][1]).split("|", 1)[1]
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    oid = row.get("outcome_id")
    sets = probs.get("sets") or {}

    if group == G_MATCH_WINNER:
        if oid == 1:
            return (probs["p1_win"], 0.0)
        if oid == 3:
            return (probs["p2_win"], 0.0)
        return None

    if group == G_SET_HANDICAP and sets:
        try:
            stored = float(line_txt)
        except (TypeError, ValueError):
            return None
        # market_key holds the line from player 1's side; player 2's own line is its
        # negation, exactly as with a football handicap.
        if oid == 5749:
            own, mine = stored, lambda s1, s2: s1 - s2
        elif oid == 5750:
            own, mine = -stored, lambda s1, s2: s2 - s1
        else:
            return None
        win = sum(p for (s1, s2), p in sets.items() if mine(s1, s2) + own > 0)
        push = sum(p for (s1, s2), p in sets.items() if mine(s1, s2) + own == 0)
        total = sum(sets.values()) or 1.0
        return (win / total, push / total)

    if group == G_TOTAL_SETS and sets:
        try:
            line = float(line_txt)
        except (TypeError, ValueError):
            return None
        total = sum(sets.values()) or 1.0
        over = sum(p for (s1, s2), p in sets.items() if s1 + s2 > line)
        if oid == 3150:
            return (over / total, 0.0)
        if oid == 3151:
            return ((total - over) / total, 0.0)
        return None

    return None
