"""Football probabilities from our own Elo model (data/model_football.json).

Produces exactly the same probability shape as engine/model_football (ClubElo), so
engine/pick.py can price ladder rungs from either source without knowing which it got:
p_home / p_draw / p_away, p_over per line, the goal-difference distribution, score_mass.

Why a second football model: ClubElo publishes only near-term fixtures for the leagues it
covers, so on a late-July card it reached 0 of 58 matches. This one is fitted from 38,598
results across 22 divisions and five seasons, and it can price any fixture whose teams it
recognises, in or out of season.

Ratings are per DIVISION and never pooled. Without cross-league fixtures a Championship
1500 and a Bundesliga 1500 are not the same strength, and merging them would silently
claim they are — so a fixture is only priced when both teams are found in the SAME
division.
"""
import difflib
import json
import os

from engine.model_football import score_matrix  # shared scoreline builder

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "model_football.json"
)

# Same noise list as the ClubElo matcher — the books and the data source spell clubs
# differently and both sides add decoration.
_NOISE = (
    "fc", "fk", "sk", "ac", "as", "sc", "cf", "cd", "ca", "afc", "cfr", "nk", "hnk",
    "mfk", "ofk", "rk", "us", "ud", "sv", "vfl", "vfb", "bsc", "if", "ff", "gif",
    "club", "kf", "ks", "fsv", "tsv", "psv", "sporting", "athletic", "atletico",
)

# football-data.co.uk uses heavy abbreviations that fuzzy matching alone will not bridge.
_ALIAS = {
    "man united": "manchester united", "man city": "manchester city",
    "nott'm forest": "nottingham forest", "sheffield weds": "sheffield wednesday",
    "wolves": "wolverhampton wanderers", "west brom": "west bromwich albion",
    "qpr": "queens park rangers", "ath madrid": "atletico madrid",
    "ath bilbao": "athletic bilbao", "sp gijon": "sporting gijon",
    "espanol": "espanyol", "betis": "real betis", "vallecano": "rayo vallecano",
    "paris sg": "paris saint germain", "ein frankfurt": "eintracht frankfurt",
    "bayern munich": "bayern munchen", "leverkusen": "bayer leverkusen",
    "m'gladbach": "borussia monchengladbach", "dortmund": "borussia dortmund",
    "ajaccio gfco": "gazelec ajaccio", "inter": "inter milan", "milan": "ac milan",
}


def _norm(name):
    s = (name or "").lower().replace(".", " ").replace("-", " ").replace("'", "'")
    s = " ".join(s.split())
    s = _ALIAS.get(s, s)
    parts = [p for p in s.split() if p and p not in _NOISE]
    return " ".join(parts) or s


def load(path=MODEL_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        model = json.load(f)
    # Pre-normalize every team name once, per division.
    for code, div in model.get("divisions", {}).items():
        div["_index"] = {_norm(t): (t, r) for t, r in div.get("ratings", {}).items()}
    return model


def _find(div, name, cutoff):
    idx = div.get("_index") or {}
    key = _norm(name)
    if key in idx:
        return idx[key], 1.0
    hit = difflib.get_close_matches(key, list(idx), n=1, cutoff=cutoff)
    if hit:
        ratio = difflib.SequenceMatcher(None, key, hit[0]).ratio()
        return idx[hit[0]], ratio
    return None, 0.0


def lookup(model, home, away, cutoff=0.86):
    """Probabilities for one fixture, or (None, 0.0) when it cannot be priced.

    BOTH teams must resolve inside the SAME division. A one-sided match is how a model
    ends up pricing a fixture that one of the teams is not playing in, and a cross-league
    match is how it ends up comparing ratings that were never on the same scale.
    """
    if not model:
        return None, 0.0
    best = None
    for code, div in model.get("divisions", {}).items():
        (h, hs), (a, asc) = _find(div, home, cutoff), _find(div, away, cutoff)
        if not h or not a or h[0] == a[0]:
            continue
        score = (hs + asc) / 2.0
        if best is None or score > best[0]:
            best = (score, code, div, h[1], a[1])
    if not best:
        return None, 0.0

    score, code, div, r_home, r_away = best
    elo_diff = r_home + (model.get("home_adv_elo") or 60.0) - r_away
    sup = div["sup_slope"] * elo_diff + div["sup_intercept"]
    total = div["mean_total"]
    lam_h = max(0.05, (total + sup) / 2.0)
    lam_a = max(0.05, (total - sup) / 2.0)
    matrix = score_matrix(lam_h, lam_a, div.get("draw_boost", 1.0))
    return _probs_from_matrix(matrix, code, elo_diff), score


def _probs_from_matrix(matrix, division, elo_diff):
    n = len(matrix)
    p_home = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
    p_draw = sum(matrix[i][i] for i in range(n))
    p_away = sum(matrix[i][j] for i in range(n) for j in range(n) if i < j)

    gd = {}
    for i in range(n):
        for j in range(n):
            gd[i - j] = gd.get(i - j, 0.0) + matrix[i][j]

    p_over = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        p_over[line] = sum(matrix[i][j] for i in range(n) for j in range(n)
                           if i + j > line)

    return {
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "p_over": p_over, "gd": gd,
        "score_mass": sum(sum(r) for r in matrix),
        "_division": division,
        "_elo_diff": round(elo_diff, 1),
        "_source": "elo",
    }
