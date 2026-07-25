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

# Corporate/legal-form tokens that carry no identity: every club has one and no club is
# distinguished by it. NOTE what is deliberately ABSENT — "atletico", "athletic" and
# "sporting" were in this list and had to come out. They are club identity, not
# decoration: stripping them collapsed "Atletico MG" to "mg" and "Sporting Gijon" to
# "gijon", which is how information gets destroyed by a cleaning step.
#
# The South American prefixes (cr, ca, ec, se, aa, sd, ad) matter most here, because the
# book writes "CR Vasco da Gama" where the results source writes "Vasco".
_NOISE = frozenset((
    "fc", "fk", "sk", "ac", "as", "sc", "cf", "cd", "ca", "afc", "cfr", "nk", "hnk",
    "mfk", "ofk", "rk", "us", "ud", "sv", "vfl", "vfb", "bsc", "if", "ff", "gif",
    "club", "kf", "ks", "fsv", "tsv", "psv", "cr", "ec", "se", "aa", "sd", "ad",
    "de", "do", "da", "of", "the", "1", "04", "05", "1899", "1900",
))

# Markers that make a team a DIFFERENT team from the senior side. Pricing a U20 or a
# women's fixture off senior ratings is not an approximation, it is the wrong team — and
# the book puts these fixtures on the same card, so it would happen constantly.
_DIFFERENT_TEAM = frozenset((
    "u17", "u18", "u19", "u20", "u21", "u23", "youth", "juniors", "junior",
    "women", "ladies", "feminine", "femenino", "feminino", "w", "reserves", "ii", "b",
    "amateur", "academy",
))

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


def _tokens(name):
    s = (name or "").lower()
    for ch in ".-'()/,":
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    s = _ALIAS.get(s, s)
    return [p for p in s.split() if p]


def _norm(name):
    parts = [p for p in _tokens(name) if p not in _NOISE]
    return " ".join(parts) or " ".join(_tokens(name))


def variant(name):
    """The age/gender/reserve variant of a team, or '' for the senior men's side.

    Two names only describe the same team if their variants agree. "Palmeiras" and
    "Palmeiras U20" share every meaningful token, so any similarity measure will call them
    a match — and the ratings would then be the senior side's.
    """
    marks = [p for p in _tokens(name) if p in _DIFFERENT_TEAM]
    return marks[0] if marks else ""


def _similarity(a_tokens, b_tokens):
    """How much two names agree, judged by shared tokens rather than character overlap.

    Sequence similarity fails on exactly the case that dominates here: one source writing
    a fuller name than the other. "cr vasco da gama" against "vasco" scores badly
    character-wise while being an obvious match, so the score is |shared| / |shorter|,
    which reads containment as agreement.
    """
    a, b = set(a_tokens), set(b_tokens)
    if not a or not b:
        return 0.0
    shared = a & b
    if not shared:
        # Fall back to character similarity for spellings that differ token by token
        # ("bayern munchen" vs "bayern munich" already share a token; "besiktas" vs
        # "besiktas jk" does too — this catches the genuinely different spellings).
        return difflib.SequenceMatcher(None, " ".join(a_tokens), " ".join(b_tokens)).ratio() * 0.9
    base = len(shared) / min(len(a), len(b))
    # A single shared token that is short and common is weak evidence on its own.
    if len(shared) == 1 and max(len(t) for t in shared) <= 3:
        base *= 0.6
    return base


def load(path=MODEL_PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        model = json.load(f)
    # Pre-tokenize every team name once, per division.
    for code, div in model.get("divisions", {}).items():
        div["_index"] = {_norm(t): (t, r) for t, r in div.get("ratings", {}).items()}
        div["_tok"] = [(t, r, _tokens(_norm(t)), variant(t))
                       for t, r in div.get("ratings", {}).items()]
    return model


def _find(div, name, cutoff):
    """Best team in this division for `name`, with its agreement score.

    An ambiguous match is refused. If the top two candidates score nearly the same, the
    name genuinely does not identify one team — Brazilian divisions are full of these
    ("Atletico GO" against "Atletico MG") and picking the higher-scoring one by a hair
    would attach the wrong club's rating rather than decline to price the fixture.
    """
    idx = div.get("_index") or {}
    key = _norm(name)
    want_variant = variant(name)
    if key in idx and variant(idx[key][0]) == want_variant:
        return idx[key], 1.0

    key_tokens = _tokens(key)
    scored = []
    for team, rating, tokens, team_variant in div.get("_tok") or []:
        if team_variant != want_variant:
            continue
        s = _similarity(key_tokens, tokens)
        if s >= cutoff:
            scored.append((s, team, rating))
    if not scored:
        return None, 0.0
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None, 0.0          # ambiguous — decline rather than guess
    s, team, rating = scored[0]
    return (team, rating), s


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
