"""Basketball probabilities from our own fitted model (data/model_basketball.json).

The margin is the whole sport, as far as this product is concerned. A basketball safety
ladder walks down plus-handicaps, and a plus-handicap is a statement about the margin and
nothing else — so unlike football, which needs a scoreline matrix to reach a goal
difference, here one normal distribution answers every question the ladder asks:

    margin ~ Normal( slope x elo_diff + intercept , residual_sd )

Fitted on 8,959 EuroLeague and EuroCup games and CALIBRATED against the observed cover
rate line by line. That calibration is not a formality: the first fit claimed 90.4% for a
+12.5 line where the real rate was 74.9%, from a sign error that produced entirely
plausible numbers. The confidence floor could never have caught it — the floor trusts the
model — so the check is the only thing standing between a sign error and a slip full of
selections the model was certain about for no reason.

Coverage is honest and narrow: EuroLeague and EuroCup clubs only. Betwinner's basketball
card spans many domestic leagues whose teams are not in this rating pool, and a fixture
this model cannot reach produces NOTHING rather than a guess.
"""
import difflib
import json
import math
import os

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "model_basketball.json")

G_1X2 = 1
G_MONEYLINE_2WAY = 101
G_HANDICAP = 2
G_ASIAN_HANDICAP = 2854
G_TOTAL = 17

O_WIN_2WAY = {1: "home", 3: "away"}
O_ML2 = {401: "home", 402: "away"}
O_HANDICAP = {7: "home", 8: "away"}
O_ASIAN = {3829: "home", 3830: "away"}
O_OVER, O_UNDER = 9, 10

# Corporate and sponsor tokens that carry no identity. Basketball is worse than football
# for this: European clubs rename themselves after their sponsor every few seasons, so
# "Fenerbahce Beko Istanbul" and "Fenerbahce" are the same club and "Anadolu Efes" has
# been "Efes Pilsen". Kept short on purpose — over-stripping is how "Atletico MG" once
# became "mg" in the football matcher.
_NOISE = frozenset((
    "bc", "kk", "cb", "bk", "basket", "basketball", "club", "sk", "ba",
    "beko", "gain", "shlomo", "cosea", "jl", "pilsen", "crvena",
))

# City tails were tried and removed. Stripping them collapsed "Real Madrid" to {real},
# which then tied with "Real Betis Energia Plus" and the matcher refused BOTH as ambiguous
# — a cleaning step that destroys the thing it is cleaning. The full noise-free token set
# keeps enough identity to separate them: {real, madrid} against {real, betis, energia}
# shares one token out of two, not one out of one.


def load(path=MODEL_PATH):
    """Index every club by its CURRENT name and by every name it has ever carried.

    A club is one rating keyed by its EuroLeague code, not one rating per sponsor era.
    The aliases exist because the book is not always current: it still writes some clubs
    the way they were called two sponsors ago, and an unmatched fixture is an unpriced
    fixture.
    """
    if not os.path.exists(path):
        return None
    with open(path) as f:
        model = json.load(f)
    model["_index"] = {}
    model["_tok"] = []
    for c in model.get("clubs") or []:
        entry = (c["name"], c["rating"])
        for alias in {c["name"], *(c.get("aliases") or [])}:
            model["_index"].setdefault(_norm(alias), entry)
            model["_tok"].append((c["name"], c["rating"], c["code"], _core(alias)))
    return model


def _tokens(name):
    s = (name or "").lower()
    for ch in ".-'()/,":
        s = s.replace(ch, " ")
    return [p for p in s.split() if p]


def _norm(name):
    parts = [p for p in _tokens(name) if p not in _NOISE]
    return " ".join(parts) or " ".join(_tokens(name))


def _core(name):
    """The identifying tokens: sponsor words removed, everything else kept."""
    parts = [p for p in _tokens(name) if p not in _NOISE]
    return set(parts or _tokens(name))


def _similarity(a, b):
    """Containment, not character overlap — one source routinely writes a longer name.

    'fenerbahce beko istanbul' against 'fenerbahce' scores badly character-wise and is an
    obvious match, so the score is |shared| / |shorter|, exactly as in the football matcher.
    """
    if not a or not b:
        return 0.0
    shared = a & b
    if not shared:
        return difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio() * 0.9
    base = len(shared) / min(len(a), len(b))
    if len(shared) == 1 and max(len(t) for t in shared) <= 3:
        base *= 0.6        # one short shared token is weak evidence on its own
    return base


def find(model, name, cutoff=0.86):
    """(team, rating), score — or (None, 0.0) when the name does not identify one club.

    An ambiguous match is refused rather than resolved by a hair. European basketball is
    full of near-collisions ('Partizan' vs 'Partizan Mozzart Bet', 'Zalgiris' vs
    'Zalgiris-2') and attaching a neighbouring club's rating is worse than not pricing the
    fixture at all.
    """
    if not model:
        return None, 0.0
    key = _norm(name)
    if key in model["_index"]:
        return model["_index"][key], 1.0

    want = _core(name)
    best = {}
    for team, rating, code, core in model["_tok"]:
        sc = _similarity(want, core)
        if sc >= cutoff and sc > best.get(code, (0.0,))[0]:
            best[code] = (sc, team, rating)
    if not best:
        return None, 0.0
    # Collapse to one row per CLUB before judging ambiguity. Two aliases of the same club
    # both scoring 1.0 is agreement, not ambiguity, and treating it as a tie is what made
    # "Fenerbahce Beko" resolve to nothing while both its own names sat in the index.
    scored = sorted(best.values(), reverse=True)
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None, 0.0
    sc, team, rating = scored[0]
    return (team, rating), sc


def _cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def lookup(model, home, away, cutoff=0.86, neutral=False):
    """Probabilities for one fixture, or (None, 0.0). BOTH teams must resolve."""
    if not model:
        return None, 0.0
    h, hs = find(model, home, cutoff)
    a, asc = find(model, away, cutoff)
    if not h or not a or h[0] == a[0]:
        return None, 0.0

    m = model["margin"]
    diff = h[1] - a[1]
    mu = m["slope"] * diff + (0.0 if neutral else m["intercept"])
    sd = m["residual_sd"] or 1.0

    t = model["total"]
    total_mu = t["mean"] + t["gap_slope"] * (abs(diff) - t["gap_mean"])
    total_sd = t["residual_sd"] or t["sd"] or 1.0

    return {
        "margin_mu": mu, "margin_sd": sd,
        "total_mu": total_mu, "total_sd": total_sd,
        "p_home": 1.0 - _cdf((0.0 - mu) / sd),
        "_elo_diff": round(diff, 1),
        "_teams": (h[0], a[0]),
        "_source": "basketball",
    }, (hs + asc) / 2.0


def rung_probs(row, probs):
    """(win, push) for a basketball selection, or None where it cannot be priced.

    Only the markets this normal actually describes are priced. Quarter and half markets
    are deliberately absent: a full-game margin distribution does not describe a quarter,
    and pricing one with the other is how an edge above +1.0 appears out of nowhere.
    """
    try:
        group, line_txt = str(row["market_key"][1]).split("|", 1)
        group = int(group)
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    oid = row.get("outcome_id")
    mu, sd = probs["margin_mu"], probs["margin_sd"]

    if group in (G_1X2, G_MONEYLINE_2WAY):
        side = O_WIN_2WAY.get(oid) if group == G_1X2 else O_ML2.get(oid)
        if side == "home":
            return (1.0 - _cdf((0.0 - mu) / sd), 0.0)
        if side == "away":
            return (_cdf((0.0 - mu) / sd), 0.0)
        return None

    if group in (G_HANDICAP, G_ASIAN_HANDICAP):
        side = (O_HANDICAP if group == G_HANDICAP else O_ASIAN).get(oid)
        if side is None:
            return None
        try:
            stored = float(line_txt)
        except (TypeError, ValueError):
            return None
        # market_key holds the line from the HOME side, as everywhere else in this
        # project; the away line is its negation.
        own = stored if side == "home" else -stored
        # Home covers when margin + own > 0; away covers when -margin + own > 0.
        if side == "home":
            win = 1.0 - _cdf((-own - mu) / sd)
        else:
            win = _cdf((own - mu) / sd)
        # A whole-number line can land exactly, but a continuous normal puts zero mass on
        # a point. Push probability is reported as zero and ALLOW_PUSH_MARKETS keeps those
        # lines out anyway — claiming a push probability here would be inventing one.
        return (win, 0.0)

    if group == G_TOTAL:
        try:
            line = float(line_txt)
        except (TypeError, ValueError):
            return None
        tmu, tsd = probs["total_mu"], probs["total_sd"]
        over = 1.0 - _cdf((line - tmu) / tsd)
        if oid == O_OVER:
            return (over, 0.0)
        if oid == O_UNDER:
            return (1.0 - over, 0.0)
        return None

    return None
