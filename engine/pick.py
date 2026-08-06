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

# Sports with a calibrated model. Everything else is counted as unmodelled rather than
# guessed at, and that count is reported.
#   10 table tennis — Setka ratings + a measured set-score distribution
# Everything else goes through engine/model_generic.py, which admits a sport only when its
# own held-out calibration says the model works. So this set is no longer the list of
# sports the product covers — it is the list of sports with a HAND-WRITTEN model, and it
# is meant to shrink.
#
# FOOTBALL LEFT IT. The hand-written Elo model is fitted on more history (298,950 results
# against 138,823) and finds 18 selections the generic one does not, but its accuracy has
# never been measured against matches it did not see. Hard rule 8 says a model is wired in
# on its calibration, not on its reach, and by that rule the generic model is the one that
# qualifies: 0.011 held out on 27,764 unseen fixtures. It offers fewer selections — 52
# against 57 — and fewer, better-evidenced selections is what this product is.
#
# TABLE TENNIS HAS NOT. Its generic store holds 88 players against the 2,007 on Setka's
# live rating index, so the generic model reaches almost nothing on a real card. The
# hand-written one stays until the store catches up.
MODELLED_SPORTS = {10}

# Sports with no home-court/home-field advantage at all — every fixture is effectively at
# a neutral site (tour tennis: whichever player is nominally "home" is just whoever sorts
# first by id, not a host). Passed to model_generic.lookup() so its HOME_ELO term is not
# added at prediction time for a sport whose training data was fitted without it either
# (every stored tennis row carries neutral=True; see engine/model_generic.fit_ratings).
# Without this a neutral sport's ratings are fitted with home advantage mostly switched
# off but every LOOKUP still added it back in — a train/predict mismatch, not a modelling
# choice, and one that quietly favours whichever side happens to sort first.
NEUTRAL_SPORTS = {4}   # tennis

# Directions to consider, in the order they are tried. Sides first: a side view is what
# the ladder can soften most, since double chance and the handicap family both exist.
DIRECTIONS = ("home", "away", "over", "under")


def _win_push(row, probs):
    """(win, push) for one selection, or None if the model cannot price it.

    Dispatches on the model that produced `probs`, because each sport prices its rungs
    from a different distribution: football from a scoreline matrix, table tennis from a
    measured set distribution. The probs dict carries its own source so the two can never
    be crossed — pricing a set handicap off a goals matrix would be silently meaningless.
    """
    from engine import model_generic, model_tt

    source = probs.get("_source")
    if source == "setka":
        return model_tt.rung_probs(row, probs)
    if source == "generic":
        return model_generic.rung_probs(row, probs)
    return model_football.rung_probs(row, probs)


def _can_push(row):
    """True when this market can return the stake rather than win or lose outright.

    Read off the LINE rather than off the model's push probability, because a model can
    put zero mass on the pushing scoreline for a particular fixture while the market still
    carries the possibility. Whole numbers push on the exact result; quarter lines split
    the stake and can push half of it. Half-lines (.5) never can, which is why they are
    the only handicaps and totals left once this is on.
    """
    try:
        group, line = str(row["market_key"][1]).split("|", 1)
        group = int(group)
    except (KeyError, ValueError, TypeError, IndexError):
        return False
    # Groups whose line is a threshold the result can land exactly on.
    if group not in (2, 2854, 17, 99, 15, 62, 8427, 8429, 7099, 2604, 109, 182):
        return False
    try:
        value = abs(float(line))
    except (TypeError, ValueError):
        return False
    return abs(value % 1 - 0.5) > 1e-9


def _survival(row, probs):
    """P(this leg does not lose the coupon) = win + push, or None if unpriceable."""
    got = _win_push(row, probs)
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
    allow_push = getattr(config, "ALLOW_PUSH_MARKETS", True)

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
            if not allow_push and _can_push(row):
                continue
            got = _win_push(row, probs)
            if not got:
                continue
            win, push = got
            surv = win + push
            if surv < min_survival:
                continue
            picked = dict(row)
            picked["ladder_rung"] = rung["label"]
            picked["ladder_scope"] = rung["scope"]
            picked["model_survival"] = round(surv, 4)
            picked["model_win"] = round(win, 4)
            picked["model_push"] = round(push, 4)
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


def resolve(sample, index=None, elo_model=None, min_name_score=0.82, tt=None,
            generic=None):
    """Probabilities for one fixture from whichever model can reach it.

    Football: our own Elo model is tried FIRST. It is fitted on 298,950 results across 39
    divisions and can price a fixture in or out of season, whereas ClubElo publishes only
    near-term fixtures for the leagues it covers. ClubElo stays as the fallback because it
    reaches competitions our division list omits, including the smaller European ties.

    Table tennis: the calibrated Setka model. Its match-winner probabilities are weak by
    design — the fit says so — but its set distribution is strong, which is where the
    ladder does its work.

    Returns (probs, name_score, source) or (None, 0.0, None).
    """
    from engine import model_elo, model_football as mf, model_generic, model_tt

    home, away = sample.get("p1"), sample.get("p2")
    sport = sample.get("sport_id")

    # The generic path first, for any sport that is not one of the two hand-written ones.
    # `generic` is a dict of already-loaded, already-admitted models — a sport whose
    # held-out calibration failed is simply not in it, so there is no way to price from a
    # model the data does not support.
    if sport not in MODELLED_SPORTS:
        model = (generic or {}).get(sport)
        if not model:
            return None, 0.0, None
        probs, score = model_generic.lookup(
            model, home, away, home_id=sample.get("p1_id"), away_id=sample.get("p2_id"),
            neutral=sport in NEUTRAL_SPORTS)
        if probs and score >= 0.86:
            return probs, score, "generic"
        return None, 0.0, None

    if sport == 10:
        # Setka's rating index FIRST, because on a measured card it reaches four times as
        # many fixtures: 70 of 350 against 18, for 11 selections against 4. The generic
        # model has the better evidence — a held-out calibration at 0.011, which the
        # hand-written one does not have at all — so hard rule 8 says it should take over,
        # and it will. What decides the order today is that Setka publishes live ratings
        # for its own circuit and the generic store is still filling.
        #
        # THE GENERIC MODEL IS THE FALLBACK RATHER THAN THE REPLACEMENT, and it is not
        # redundant: it now holds Pro League, Masters and TT-Cup players from the live
        # watcher, which Setka's index does not carry at all. So the two cover different
        # parts of the same card. Running them in sequence was checked before it was wired
        # in — where both priced the same fixture they agreed on the direction AND on the
        # ladder rung every time, so this adds reach without mixing two opinions.
        # tools/compare_models.py re-runs that check; when the generic side wins on reach
        # as well, swap the order and delete the hand-written model.
        if tt:
            probs, score = model_tt.lookup(tt[0], tt[1], home, away)
            if probs:
                return probs, score, "setka"
        model = (generic or {}).get(sport)
        if model:
            probs, score = model_generic.lookup(
                model, home, away,
                home_id=sample.get("p1_id"), away_id=sample.get("p2_id"))
            if probs and score >= 0.86:
                return probs, score, "generic"
        return None, 0.0, None

    if sport == 1:
        if elo_model:
            probs, score = model_elo.lookup(elo_model, home, away)
            if probs and score >= 0.86:
                return probs, score, "elo"
        if index:
            probs, score = mf.lookup(index, home, away, cutoff=min_name_score)
            if probs and score >= min_name_score:
                return probs, score, "clubelo"
    return None, 0.0, None


def for_fixtures(rows, index=None, elo_model=None, min_odds=None, min_survival=None,
                 min_name_score=0.82, tt=None, generic=None):
    """Run the whole selection over a scan's worth of rows, one pick per match.

    `rows` should be UNFILTERED normalized rows, not the scored top-N: the ladder needs
    alternative lines, and every plus-handicap and every non-headline total is an alt line.
    """
    by_match = {}
    for r in rows:
        if r.get("sub_game"):
            # Full-match probabilities do not describe a half or a corners market. Pricing
            # one with the other produced edges above +1.0 before it was caught.
            continue
        by_match.setdefault(r.get("match_id", r["fixture_id"]), []).append(r)

    picks = []
    skipped = {"no_model": 0, "no_confident_rung": 0, "unmodelled_sport": 0}
    for match_id, match_rows in by_match.items():
        sample = match_rows[0]
        sport = sample.get("sport_id")
        if sport not in MODELLED_SPORTS and sport not in (generic or {}):
            skipped["unmodelled_sport"] += 1
            skipped.setdefault("by_sport", {})
            skipped["by_sport"][sport] = skipped["by_sport"].get(sport, 0) + 1
            continue
        probs, name_score, source = resolve(sample, index, elo_model, min_name_score,
                                           tt, generic)
        if not probs:
            # The biggest bucket on a real card by a long way, and the one the coverage
            # report has to break down by sport: it is not "we did not look", it is "we
            # looked and our history does not contain these two teams". Those are opposite
            # problems with opposite fixes.
            skipped["no_model"] += 1
            skipped.setdefault("no_model_by_sport", {})
            skipped["no_model_by_sport"][sport] = (
                skipped["no_model_by_sport"].get(sport, 0) + 1)
            # And WHICH competitions, because that is the actionable half. On a real card
            # the answer is Pro League table tennis, ITF qualifying, Finnish fourth-tier
            # football and Uruguayan second-division basketball — lower-tier, youth,
            # women's and qualifying events that no free archive covers at all. Knowing
            # that is what stops the next week being spent hunting for one.
            league = sample.get("league")
            if league:
                skipped.setdefault("no_model_leagues", {})
                key = f"{sport}|{league}"
                skipped["no_model_leagues"][key] = (
                    skipped["no_model_leagues"].get(key, 0) + 1)
            continue
        chosen = best(match_rows, sample["sport_id"], probs, min_odds, min_survival)
        if not chosen:
            skipped["no_confident_rung"] += 1
            skipped.setdefault("no_rung_by_sport", {})
            skipped["no_rung_by_sport"][sport] = (
                skipped["no_rung_by_sport"].get(sport, 0) + 1)
            continue
        chosen["name_match"] = round(name_score, 3)
        chosen["model_source"] = source
        chosen["division"] = probs.get("_division")
        # How much history stands behind this particular call. Two picks at the same
        # stated confidence are not equally well founded — one may rest on a division
        # fitted from 900 matches and the other from 12,000 — and engine/rating.py turns
        # that difference into the evidence half of the score.
        chosen["model_n"] = probs.get("_n")
        div = ((elo_model or {}).get("divisions") or {}).get(probs.get("_division") or "")
        chosen["division_matches"] = (div or {}).get("matches")
        if source == "generic":
            # How much history stands behind THIS band, so the evidence half of the score
            # reads a real number rather than the size of the whole sport.
            chosen["division_matches"] = probs.get("sample_n")
        picks.append(chosen)

    picks.sort(key=lambda r: -r["model_survival"])
    return picks, skipped
