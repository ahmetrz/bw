"""ONE model for every sport, fitted from data/results/<sport>.jsonl and nothing else.

This replaces the pattern that was making the product impossible to finish. Football got a
Poisson pair with a fitted draw correction; table tennis got a measured set distribution;
basketball got a normal margin. Three sports, three sets of maths, three chances to be
wrong — and both bugs that reached a live card came from exactly that duplication: a sign
error in the basketball handicap, and a table tennis logistic extrapolated past the range
it was fitted on. The book carries 47 sports with fixtures inside 48 hours. Written this
way, the product never covers its own card.

So there is no distribution assumed here at all. The model IS the observed record:

    1. Elo from results, with a margin-of-victory term. Universal — it needs only who
       played whom and by how much.
    2. The rating gap maps to an expected margin by least squares — a straight line, and
       the ONLY thing fitted. What is left over, the residual, is COUNTED rather than
       assumed: not Poisson, not normal, not logistic. Whatever the sport actually does is
       what comes out, so a sport with a fat draw (chess), a sport that cannot draw
       (basketball) and a sport scored in sets (volleyball) all work with the same code and
       none of them needs a modelling decision.

       Bucketing the gap was tried first and lost too much: inside one bucket a gap of 45
       and a gap of 89 were priced identically, and both football and basketball then
       over-predicted the underdog by about three points. Using the gap continuously and
       counting only what the line fails to explain keeps the honesty and recovers the
       precision.
    3. Calibration falls out of the same table, and `usable()` REFUSES a sport whose
       predictions do not match its observations. A sport is not modelled because someone
       wired it up; it is modelled when its own data says the model works.

Counting instead of fitting also removes a whole class of error. Basketball's sign bug
could not have happened here: the probability of covering +12.5 is the share of observed
margins that covered +12.5, and there is no expression to get backwards.

Standard library only.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "data", "models")

START_RATING = 1500.0
K = 20.0
SEASON_REGRESSION = 0.25
HOME_ELO = 60.0

# How many bands of expected margin the record is split into. The edges are QUANTILES of
# the fixtures themselves, not fixed numbers, so one setting works for goals, points and
# sets without anybody choosing a scale.
N_BANDS = 12

# A band thinner than this is not a measurement, so the band count is reduced until every
# band clears it. A band of 30 matches will happily report that a line covers 100% of the
# time, and that is exactly the shape of claim a confidence floor waves through.
MIN_BAND = 400

# How many matches a team or player must have behind its rating before that rating is
# allowed to price anything. A side seen twice still sits near the 1500 it started at, and
# 1500 does not mean "average" for that side — it means "we have not measured it". Pricing
# from it makes every mismatch look like a coin flip, which is precisely how tennis first
# failed its calibration by 7.4 points at +0.5: the tour is full of qualifiers who appear
# once, and each of them was being treated as a solid mid-table player.
MIN_APPEARANCES = 20

# The result markets, which mean the same thing in every sport.
G_1X2, G_MONEYLINE_2WAY, G_DOUBLE_CHANCE = 1, 101, 8
O_DC_HOME_OR_DRAW, O_DRAW, O_DC_DRAW_OR_AWAY = 4, 2, 6
O_WIN_2WAY = {1: "home", 3: "away"}
O_ML2 = {401: "home", 402: "away"}
O_OVER, O_UNDER = 9, 10

# THE UNIT MATTERS AND IT IS NOT COSMETIC. A distribution answers questions asked in its
# own unit and no others. The store records table tennis and tennis in SETS, so the book's
# group 17 — "total 76.5", a POINTS market — must never be priced from it: every set total
# ever recorded is between 3 and 5, so "under 76.5" comes back certain. That is not a
# rounding error, it is a 100.00% claim on a 1.79 shot, and it happened.
#
# So each unit declares which market groups it is allowed to answer. A group that is not
# listed for the sport's unit is refused, not approximated.
HANDICAP_GROUPS = {
    "goals":  {2: {7: "home", 8: "away"}, 2854: {3829: "home", 3830: "away"}},
    "points": {2: {7: "home", 8: "away"}, 2854: {3829: "home", 3830: "away"}},
    "runs":   {2: {7: "home", 8: "away"}, 2854: {3829: "home", 3830: "away"}},
    # Set handicaps: 109 is tennis AND volleyball, 7099 table tennis. The POINT handicap
    # (group 2) is a different bet in these sports and is deliberately absent — volleyball
    # quotes it at ±10.5, which is a rally count, not a set count.
    "sets":   {109: {732: "home", 733: "away"}, 7099: {5749: "home", 5750: "away"}},
    # Snooker counts frames and quotes them on the ORDINARY handicap group, so the group
    # id alone cannot say what the line means — only the sport's declared unit can.
    "frames": {2: {7: "home", 8: "away"}},
    # Esports has its own map handicap. Group 2 there is a ROUND handicap and is excluded
    # for the same reason volleyball's is.
    "maps":   {2438: {2826: "home", 2827: "away"}},
}
TOTAL_GROUPS = {
    "goals": {17}, "points": {17}, "runs": {17},
    # 182 is total sets in tennis and volleyball, 2604 in table tennis. Group 17 for these
    # sports counts points or games and is NOT what this distribution measures.
    "sets": {182, 2604},
    # Snooker total frames; esports total maps. Group 17 in esports is a total of ROUNDS
    # (51.5 on a CS2 fixture), which a maps distribution would price as a certainty.
    "frames": {876},
    "maps": {2436},
}


def unit_of(model):
    """What the stored scores count. Declared by the adapter; inferred only as a backstop.

    The inference is deliberately crude and conservative: a sport whose biggest observed
    total is 8 or fewer is scored in sets. Football reaches double figures, basketball the
    high two hundreds; nothing scored in goals or points sits down there.
    """
    unit = model.get("unit")
    if unit:
        return unit
    biggest = 0
    for bands in (model.get("bands") or {}).values():
        for b in bands:
            for t in b.get("total") or {}:
                biggest = max(biggest, abs(float(t)))
    return "sets" if biggest <= 8 else "points"


def model_path(sport_id):
    return os.path.join(MODELS, f"{int(sport_id)}.json")


# --------------------------------------------------------------------------- fitting

def _expected(diff):
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def team_key(row, side):
    """Who a team IS. A stable id when the source has one, the name otherwise.

    This is the general form of a lesson basketball taught expensively: keyed by name,
    167 clubs became 343 rating entries because European clubs rename after their sponsor,
    and every one of those entries held a fragment of one club's history. An id survives a
    rename and a name never does, so an adapter that has one supplies it and this uses it.
    """
    return row.get(f"{side}_id") or row[side]


def name_map(rows):
    """(pool, key) -> most recent name, plus every other name it has appeared under."""
    latest, aliases = {}, {}
    for r in sorted(rows, key=lambda x: x["date"]):
        for side in ("home", "away"):
            k = (pool_of(r), team_key(r, side))
            latest[k] = r[side]
            aliases.setdefault(k, set()).add(r[side])
    return latest, {k: sorted(v) for k, v in aliases.items()}


def pool_of(row):
    """The rating scale a result belongs to. Absent means the sport has a single scale."""
    return row.get("pool") or ""


def fit_ratings(rows, record=False):
    """Chained Elo, PER RATING POOL. Returns the final ratings, or (final, pre-match gaps).

    `record` gives back the effective rating gap AS IT STOOD BEFORE each match, which is
    the only gap a model could ever have had at prediction time. Fitting the distributions
    on final ratings instead is hindsight: every match is then described by how good the
    two sides turned out to be over the whole history, including that match and everything
    after it. It flatters the fit and, worse, it distorts it — the model was systematically
    over-rating underdogs at the tightest line in football, basketball and tennis alike
    until this was separated out.

    Pooling everything was tried first and football failed its own calibration by 4.8
    points at +0.5 — 22 divisions had been averaged onto one scale, so a mid-table
    League Two side and a mid-table Premier League side were being called equals. The
    calibration gate caught it, which is the entire reason the gate exists: generalizing a
    model is exactly the moment a sport's real structure gets dropped.
    """
    rating, year, gaps = {}, None, []
    for r in sorted(rows, key=lambda x: x["date"]):
        y = r["date"][:4]
        if year is not None and y != year:
            for t in rating:
                rating[t] += (START_RATING - rating[t]) * SEASON_REGRESSION
        year = y
        pool = pool_of(r)
        h, a = (pool, team_key(r, "home")), (pool, team_key(r, "away"))
        rating.setdefault(h, START_RATING)
        rating.setdefault(a, START_RATING)
        margin = r["home_score"] - r["away_score"]
        diff = rating[h] - rating[a] + (0.0 if r.get("neutral") else HOME_ELO)
        if record:
            gaps.append(diff)
        actual = 1.0 if margin > 0 else (0.5 if margin == 0 else 0.0)
        mov = math.log(abs(margin) + 1.0) * (2.2 / (abs(diff) * 0.001 + 2.2))
        delta = K * mov * (actual - _expected(diff))
        rating[h] += delta
        rating[a] -= delta
    return (rating, gaps) if record else rating


def fit_line(rows, gaps):
    """expected margin = a + b x effective rating gap, by least squares. Universal.

    `gaps` are the PRE-MATCH gaps from fit_ratings(record=True), in the same order as the
    date-sorted rows they came from.
    """
    xs, ys = list(gaps), []
    for r in sorted(rows, key=lambda x: x["date"]):
        ys.append(float(r["home_score"] - r["away_score"]))
    n = len(xs) or 1
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    return {"slope": slope, "intercept": my - slope * mx, "n": n,
            "mean_abs_margin": sum(abs(y) for y in ys) / n}


def expected_margin(line, gap):
    return line["slope"] * gap + line["intercept"]


def fit_bands(rows, gaps, line, by_pool=True):
    """Bands PER POOL, with the sport-wide set as the fallback for thin pools.

    A pool is not only a rating scale, it is usually a different game. Tennis mixes
    best-of-3 and best-of-5: a Bo5 match can end 3-0 in sets and a Bo3 one never can, so
    pooling their margins puts outcomes into a distribution that cannot produce them, and
    "+2.5 sets" means two different bets in the two formats. Football divisions score at
    2.37 to 3.18 goals a game, which moves every totals line. Splitting the bands costs
    nothing where a pool is thick and falls back to the sport-wide record where it is not.
    """
    if not by_pool:
        return _bands_from(rows, gaps, line)
    by = {}
    for r, g in zip(sorted(rows, key=lambda x: x["date"]), gaps):
        by.setdefault(pool_of(r), []).append((r, g))
    out = {"": _bands_from(rows, gaps, line)}
    for pool, items in by.items():
        if len(items) >= MIN_BAND * 2:
            out[pool] = _bands_from([r for r, _ in items], [g for _, g in items], line)
    return out


def _bands_from(rows, gaps, line):
    """Counted margin and total distributions, per band of EXPECTED margin.

    The actual integer margins are counted, never a residual that gets shifted back. That
    was tried and it broke football: shifting an integer residual by a fractional expected
    margin lands mass on impossible scorelines like 0.4, the draw spike smears across them,
    and the model then over-predicted "the underdog does not lose" by five points at +0.5.
    A distribution over margins has to stay a distribution over margins that can happen.

    Banding on the EXPECTED margin rather than on the raw rating gap is what makes this
    work across sports: the expected margin is already in the sport's own units, so one
    band count covers goals, points and sets with no scale set by hand.
    """
    rows = sorted(rows, key=lambda x: x["date"])
    mus = [expected_margin(line, g) for g in gaps]
    order = sorted(range(len(rows)), key=lambda i: mus[i])
    n_bands = N_BANDS
    while n_bands > 1 and len(rows) / n_bands < MIN_BAND:
        n_bands -= 1

    bands, size = [], max(1, len(order) // n_bands)
    for b in range(n_bands):
        lo = b * size
        hi = len(order) if b == n_bands - 1 else (b + 1) * size
        idx = order[lo:hi]
        if not idx:
            continue
        margin, total = {}, {}
        for i in idx:
            r = rows[i]
            m = r["home_score"] - r["away_score"]
            margin[str(m)] = margin.get(str(m), 0) + 1
            t = r["home_score"] + r["away_score"]
            total[str(t)] = total.get(str(t), 0) + 1
        bands.append({
            "lo": round(mus[idx[0]], 4), "hi": round(mus[idx[-1]], 4),
            "n": len(idx), "margin": margin, "total": total,
        })
    return bands


def band_index(bands, mu):
    """The band whose expected-margin range contains mu, clamped at both ends."""
    for i, b in enumerate(bands):
        if mu <= b["hi"]:
            return i
    return len(bands) - 1


# --------------------------------------------------------------------------- pricing

def _pmf(counts):
    tot = sum(counts.values()) or 1
    return {float(k): v / tot for k, v in counts.items()}


def p_margin_over(pmf, line):
    """P(favourite margin > line). The line may be fractional; the sum handles it."""
    return sum(p for m, p in pmf.items() if m > line)


def p_total_over(pmf, line):
    return sum(p for t, p in pmf.items() if t > line)


def load(sport_id):
    p = model_path(sport_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        model = json.load(f)
    bands = model["bands"]
    if isinstance(bands, list):          # models written before bands were pooled
        bands = {"": bands}
        model["bands"] = bands
    model["_margin"] = {k: [_pmf(b["margin"]) for b in v] for k, v in bands.items()}
    model["_total"] = {k: [_pmf(b["total"]) for b in v] for k, v in bands.items()}
    return model


def margin_pmf(model, gap, pool=""):
    """The margin distribution for one fixture, from the HOME side.

    The whole model in two steps: the rating gap says what margin to expect, and the band
    of fixtures with a similar expectation says what actually happened. There is no sign to
    get backwards — P(covers +12.5) is the share of those matches that covered +12.5.
    """
    mu = expected_margin(model["line"], gap)
    key = pool if pool in model["bands"] else ""
    i = band_index(model["bands"][key], mu)
    return model["_margin"][key][i], mu, (key, i)


# The least history a sport can be admitted on. Named rather than inline because the
# coverage report now tells the operator how far a sport still has to go, and a target
# quoted from one place and enforced from another eventually disagree.
MIN_RESULTS = 400


def usable(model, max_gap=0.03):
    """Is this sport's model good enough to be allowed to price anything?

    The gate the product was missing. A model is admitted on its measured agreement with
    its own history, not on the fact that somebody wired it in — which is how a sign error
    and an extrapolated logistic both reached a live card.
    """
    if not model:
        return False, "no model"
    cal = model.get("calibration") or []
    if not cal:
        return False, "no calibration table"
    if model.get("games", 0) < MIN_RESULTS:
        return False, f"only {model.get('games', 0)} results"
    worst = max(abs(c["predicted"] - c["observed"]) for c in cal)
    if worst > max_gap:
        return False, f"calibration off by {worst:.3f}"
    return True, f"{model['games']} results, worst calibration gap {worst:.3f}"


def appearances(model, pool, team):
    return ((model.get("appearances") or {}).get(pool) or {}).get(team, 0)


def lookup(model, home, away, matcher=None, home_id=None, away_id=None):
    """Probabilities for one fixture, or (None, 0.0) when it cannot be priced honestly.

    BOTH teams must resolve inside the SAME pool. A cross-pool comparison is how a model
    ends up rating a Championship side against a Bundesliga side on a scale neither of
    them has ever been measured on.

    When the card and the store share the BOOK'S participant id, that wins outright and
    the names are not consulted. Name matching is the weakest link in this whole path: it
    needs a fuzzy threshold, it needs a guard against "(Women)" and "U20" resolving to the
    senior side — a guard that was once dropped and immediately priced a women's fixture
    at 99.78% off the men's ratings — and it still fails on a transliteration or a sponsor
    rename. An id has none of those failure modes. It is available for every fixture the
    live watcher collected, because it comes off the same feed the card is built from.
    """
    if not model:
        return None, 0.0
    match = matcher or exact_matcher(model)
    best = None
    ids = model.get("book_ids") or {}
    for pool in model["pools"]:
        by_id = ids.get(pool) or {}
        h = by_id.get(str(home_id)) if home_id else None
        a = by_id.get(str(away_id)) if away_id else None
        hs = asc = 1.0
        if h is None:
            h, hs = match(home, pool)
        if a is None:
            a, asc = match(away, pool)
        if h is None or a is None or h == a:
            continue
        # A provisional rating is not a rating. Refusing here costs a selection; pricing
        # from it costs a wrong one, presented with the same confidence as a right one.
        if min(appearances(model, pool, h), appearances(model, pool, a)) < MIN_APPEARANCES:
            continue
        score = (hs + asc) / 2.0
        if best is None or score > best[0]:
            best = (score, pool, h, a)
    if best is None:
        return None, 0.0
    score, pool, h, a = best
    ratings = model["pools"][pool]
    eff = ratings[h] - ratings[a] + HOME_ELO
    pmf, mu, band = margin_pmf(model, eff, pool)
    return {
        # From the HOME side, always. The old version stored it from the favourite's view
        # and every caller then had to remember which side that was — a flip waiting to
        # happen, and this project has already shipped one.
        "margin_pmf": pmf,
        "total_pmf": model["_total"][band[0]][band[1]],
        "expected_margin": round(mu, 3),
        "sample_n": model["bands"][band[0]][band[1]]["n"],
        "band": band[1],
        "_elo_diff": round(eff, 1),
        "_teams": (h, a),
        "unit": unit_of(model),
        "_pool": pool,
        "_pool_n": len(ratings),
        "_sport": model.get("sport_id"),
        "_source": "generic",
    }, score


def exact_matcher(model):
    """One name index per pool, built once and reused for every fixture on the card."""
    indexes = {}
    for pool, ratings in model["pools"].items():
        idx = {_norm(t): t for t in ratings}
        for alias, target in (model.get("aliases") or {}).get(pool, {}).items():
            idx.setdefault(_norm(alias), target)
        indexes[pool] = idx

    def match(name, pool):
        idx = indexes.get(pool) or {}
        key = _norm(name)
        want = variant(name)
        if key in idx and variant(idx[key]) == want:
            return idx[key], 1.0
        return _fuzzy(idx, key, want=want)
    return match


# Markers that make a team a DIFFERENT team from the senior side. This guard exists in
# engine/model_elo.py and was dropped when the matcher was generalized, which is exactly
# the kind of thing generalizing loses. The cost was visible immediately: the generic
# football model priced "Corinthians Paulista (Women)" from the MEN'S Brazilian Serie A
# ratings and called a +6.5 handicap 99.78%, and did the same for three Danish, Scottish
# and Brazilian U20 fixtures. That is not an approximation, it is the wrong team — and the
# book puts these on the same card as the senior fixtures, so it happens constantly.
_VARIANT = frozenset((
    "u16", "u17", "u18", "u19", "u20", "u21", "u23", "youth", "juniors", "junior",
    "women", "woman", "ladies", "feminine", "femenino", "feminino", "femminile", "w",
    "reserves", "reserve", "ii", "b", "amateur", "academy", "development",
))


def variant(name):
    """The age or gender variant of a team, or "" for the senior side.

    Two names only describe the same team if their variants AGREE. "Palmeiras" and
    "Palmeiras U20" share every meaningful token, so any similarity measure will call them
    a match — and the ratings attached would be the senior side's.
    """
    for token in _norm(name).split():
        if token in _VARIANT:
            return token
    return ""


def _norm(name):
    s = (name or "").lower()
    for ch in ".-'()/,":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _fuzzy(index, key, cutoff=0.86, want=""):
    """Containment on tokens, refusing a tie. Same rule as the football matcher.

    Refusing is the point. Attaching a neighbouring team's rating is worse than declining
    to price the fixture, because a wrong rating produces a confident wrong answer.

    `want` is the variant the fixture asked for. A candidate whose variant differs is not
    a worse match, it is a different team, so it is dropped rather than scored.
    """
    tokens = set(key.split())
    if not tokens:
        return None, 0.0
    best = []
    for norm, team in index.items():
        if variant(team) != want:
            continue
        have = set(norm.split())
        shared = tokens & have
        if not shared:
            continue
        score = len(shared) / min(len(tokens), len(have))
        if len(shared) == 1 and max(len(t) for t in shared) <= 3:
            score *= 0.6
        if score >= cutoff:
            best.append((score, team))
    if not best:
        return None, 0.0
    best.sort(reverse=True)
    if len({t for _, t in best}) > 1 and best[0][0] - best[1][0] < 0.05:
        return None, 0.0
    return best[0][1], best[0][0]


def rung_probs(row, probs):
    """(win, push) for any selection the ladder can build, in any sport.

    Everything is read off the counted margin distribution, so a market is priced only
    when the record actually answers it. Sub-game markets never arrive here — engine/pick
    drops them — because a full-match distribution does not describe a half.
    """
    try:
        group, line_txt = str(row["market_key"][1]).split("|", 1)
        group = int(group)
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    oid = row.get("outcome_id")
    pmf = probs["margin_pmf"]          # always from the HOME side
    unit = probs.get("unit") or "points"
    n = max(1, probs.get("sample_n") or 1)

    def side_pmf(side):
        return pmf if side == "home" else {-m: p for m, p in pmf.items()}

    def cap(p):
        """A counted probability may never be exactly 0 or 1.

        "Never observed in 621 matches" is not "impossible", and a 1.000 sails through
        every gate this product has. Laplace's rule keeps the claim inside what the sample
        can actually support; on a large band the correction is invisible, on a small one
        it is the whole point.

        Clamped at BOTH ends, symmetrically, because the two sides of a half-line have to
        keep summing to 1. Capping only the top broke that: one side came back at 0.967
        and its mirror at 0.000, which is not a probability pair, it is two numbers.
        """
        floor = 1.0 / (n + 2.0)
        return min(max(p, floor), 1.0 - floor)

    if group in (G_1X2, G_MONEYLINE_2WAY):
        side = O_WIN_2WAY.get(oid) if group == G_1X2 else O_ML2.get(oid)
        if side is None:
            if group == G_1X2 and oid == O_DRAW:
                return (sum(p for m, p in pmf.items() if abs(m) < 1e-9), 0.0)
            return None
        sp = side_pmf(side)
        return (cap(p_margin_over(sp, 0.0)), 0.0)

    if group == G_DOUBLE_CHANCE:
        side = {O_DC_HOME_OR_DRAW: "home", O_DC_DRAW_OR_AWAY: "away"}.get(oid)
        if side is None:
            return None
        sp = side_pmf(side)
        return (cap(p_margin_over(sp, -0.5)), 0.0)      # wins or draws

    if group in HANDICAP_GROUPS.get(unit, {}):
        side = HANDICAP_GROUPS[unit][group].get(oid)
        if side is None:
            return None
        try:
            stored = float(line_txt)
        except (TypeError, ValueError):
            return None
        own = stored if side == "home" else -stored
        sp = side_pmf(side)
        win = sum(p for m, p in sp.items() if m + own > 0)
        push = sum(p for m, p in sp.items() if abs(m + own) < 1e-9)
        return (cap(win), push)

    if group in TOTAL_GROUPS.get(unit, set()):
        try:
            line = float(line_txt)
        except (TypeError, ValueError):
            return None
        over = p_total_over(probs["total_pmf"], line)
        if oid == O_OVER:
            return (cap(over), 0.0)
        if oid == O_UNDER:
            push = probs["total_pmf"].get(line, 0.0)
            return (cap(1.0 - over - push), push)
        return None

    # Anything else — a points handicap in a set-scored sport, a corner market, a market
    # this record simply does not describe — is refused rather than approximated.
    return None
