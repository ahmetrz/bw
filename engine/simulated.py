"""Spot a league that is GENERATED rather than played, from its structure alone.

    from engine import simulated
    bad = simulated.leagues(rows)      # {(sport_id, league): reason}

WHAT THIS IS FOR. `config.EXCLUDED_SPORTS` already removes whole sports that are obviously
not contests — the marble ladders, the FIFA leagues, the lotto draws. What it cannot catch
is a GENERATED COMPETITION FILED UNDER A REAL SPORT: "UPVL. Nations League" sits in
volleyball, "RHL" sits in ice hockey, and both look like ordinary entries on the card.
Left alone they reach the results store, and a rating fitted on invented results is worse
than no rating — the model would be confident about teams that never played.

PRICE IS NOT THE SIGNAL, and that was the first thing tried. On a real card, six RHL
fixtures carried BYTE-IDENTICAL prices across all 35 markets, which looked decisive until
the same test flagged Setka Cup: four of its fixtures were identical across 33 markets
too. Setka Cup is the circuit behind 25,738 stored results and a 0.011 calibration. The
book simply templates prices for any low-liquidity market, real or not, so a price-based
rule would have deleted the best-evidenced sport in the project. Start-time regularity
failed the same way — Setka Cup genuinely runs every fifteen minutes, and so does the
KeSPA Cup.

THE ROUND-ROBIN SHAPE IS NOT THE SIGNAL EITHER, and that was the second thing tried:

    RHL     02:50 Berkut v Phoenix · 03:30 Phoenix v Elektronik · 04:20 Elektronik v Berkut
    UPVL    03:10 Argentina v Spain · 04:10 USA v Argentina · 05:15 Spain v USA

Three participants, every pair played once, the whole group over inside two hours. It
looks damning until you run it across the card and it flags Setka Cup Czech Republic and
Setka Cup Moldova — because Setka Cup ALSO runs four-player round-robin groups in two and
a half hours. That is simply how the circuit works, and it is the circuit behind 25,738
stored results.

THE SIGNAL IS PHYSICAL IMPOSSIBILITY. What separates the two is not the shape of the
schedule but whether a body could keep it:

    Berkut Volgograd starts at 02:50 and again at 04:20. Ninety minutes apart. An ice
    hockey game is three twenty-minute periods with two intermissions; it is not over in
    ninety minutes, so the second game starts while the first is still being played.

    Argentina Pro starts at 03:10 and again at 04:10. A volleyball match swept 3-0 runs
    past seventy minutes before anyone leaves the court.

    A Setka Cup player's matches sit thirty minutes apart, and a best-of-five table tennis
    match is done in eighteen. Nothing impossible about it.

So the test is: does any participant start a second fixture before their previous one
could possibly have ended? That is a fact about the sport, not a statistic about the
league, so it cannot be fooled by a small sample or a coarse price grid — and it reads no
prices at all, which keeps hard rule 6 clean.
"""
import collections
from datetime import datetime

# The shortest a match of this sport could possibly take, in hours, INCLUDING the walk
# off court. Deliberately conservative — every value here is shorter than the sport's real
# typical length, because the rule must only fire on the impossible, never on the merely
# quick. A false positive deletes a real competition from the model's history.
MIN_MATCH_HOURS = {
    1: 1.75,   # football — two 45s plus the half
    2: 2.0,    # ice hockey — three 20s plus two intermissions
    3: 1.5,    # basketball
    4: 0.75,   # tennis — a 6-0 6-0 is about fifty minutes
    5: 2.0,    # baseball
    6: 1.25,   # volleyball — a 3-0 sweep still runs past seventy minutes
    8: 1.25,   # handball
    10: 0.3,   # table tennis — a best-of-five can be done in eighteen minutes
    12: 0.5,   # billiards
    13: 2.0,   # american football
    14: 1.25,  # futsal
    16: 0.4,   # badminton
    17: 1.25,  # water polo
    21: 0.5,   # darts
    27: 1.25,  # field hockey
    29: 0.6,   # beach volleyball
    30: 0.6,   # snooker
    40: 0.75,  # esports
    48: 1.5,   # lacrosse
    49: 1.0,   # netball
    66: 2.5,   # cricket
    282: 0.3,  # padel — five short sets to eleven points
    283: 0.3,  # pickleball
}
DEFAULT_MIN_MATCH_HOURS = 1.0


def _epoch(value):
    """Seconds from an ISO start stamp, or None when there is no readable time.

    None rather than 0: a fixture with an unreadable start must be skipped, and a
    fixture at epoch zero must not be — conflating them silently dropped the first
    fixture of every group and halved the evidence this rule runs on.
    """
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None

# One participant double-booked could be the book mislabelling a fixture. Several is the
# schedule itself being impossible.
MIN_OFFENDERS = 2


def impossible_schedule(fixtures, sport_id):
    """(True, reason) when participants are booked to play before they could have finished.

    `fixtures` is [(participant, participant, start epoch)] for ONE competition.
    """
    need = MIN_MATCH_HOURS.get(sport_id, DEFAULT_MIN_MATCH_HOURS)
    when = collections.defaultdict(list)
    for a, b, start in fixtures:
        if start is None:
            continue
        when[a].append(start)
        when[b].append(start)

    offenders, tightest = set(), None
    for who, starts in when.items():
        starts.sort()
        for first, second in zip(starts, starts[1:]):
            gap = (second - first) / 3600.0
            if gap < need:
                offenders.add(who)
                tightest = gap if tightest is None else min(tightest, gap)
    if len(offenders) < MIN_OFFENDERS:
        return False, ""
    return True, (f"{len(offenders)} katılımcı, bir öncekini bitirmesi mümkün olmadan "
                  f"({tightest * 60:.0f} dk arayla, en az {need * 60:.0f} dk sürer) "
                  f"tekrar sahaya çıkıyor — üretilmiş fikstür")


STORE = "data/simulated_leagues.json"


def save(found, path=STORE):
    """Write the flagged competitions where the live watcher can read them.

    The pattern is only visible across a whole card, which the daily run has and a
    two-minute live sweep does not. So the daily run decides and the watcher obeys.
    """
    import json
    import os

    payload = sorted([{"sport_id": sid, "league": league, "why": why}
                      for (sid, league), why in (found or {}).items()],
                     key=lambda r: (r["sport_id"] or 0, r["league"] or ""))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return len(payload)


def load(path=STORE):
    """{(sport_id, league): why}, or empty when nothing has been flagged yet."""
    import json

    try:
        with open(path) as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {(r.get("sport_id"), r.get("league")): r.get("why") or ""
            for r in rows or [] if r.get("league")}


def leagues(rows, key=lambda r: (r.get("sport_id"), r.get("league"))):
    """Every competition on a card that shows the generated-cycle shape.

    Takes normalized rows and returns {(sport_id, league): reason}. Fixtures are
    identified by participant, and by the book's participant ids where present — a name is
    enough here, but an id cannot be spelled two ways.
    """
    by_league = collections.defaultdict(dict)
    for r in rows:
        if r.get("sub_game"):
            continue
        mid = r.get("match_id", r.get("fixture_id"))
        a = r.get("p1_id") or r.get("p1")
        b = r.get("p2_id") or r.get("p2")
        when = _epoch(r.get("start"))
        if a and b and when is not None:
            by_league[key(r)][mid] = (str(a), str(b), when)
    out = {}
    for k, fixtures in by_league.items():
        bad, why = impossible_schedule(list(fixtures.values()), k[0])
        if bad:
            out[k] = why
    return out
