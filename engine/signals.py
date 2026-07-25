"""Which statistic informs which bet, what it means for that bet, and whether we HAVE it.

The research files under research/ already map bet type -> statistics for all 64 sports.
That knowledge was never wired into the engine, so the analysis ran on goals and results
alone while the mapping sat in documents. This module is that mapping made executable, and
— more importantly — made honest: every signal carries its STATUS, so the difference
between "we know this matters" and "we actually use it" is visible instead of implied.

    status = "live"       computed from data we hold, and feeding the model today
             "available"  a free source is verified, but it is not wired in yet
             "missing"    no free source found, or the source is robots-disallowed

`direction` says what the statistic MEANS for that market, which is the part a bare list
of stat names leaves out. "Shots on target" is not simply "relevant to totals" — a high
combined rate pushes the over, and the same number split unevenly pushes a handicap
instead. Without that, a mapping cannot drive an analysis.

The point of the status field is to make the roadmap fall out of the data: anything marked
`available` is work that is already justified, and the gap between live and available is
the honest measure of how far the product is from using what it knows.
"""

# Betwinner market groups, as decoded in engine/bwfeed.py.
MARKETS = {
    1: "1X2",
    101: "moneyline (2-way)",
    8: "double chance",
    2: "handicap",
    2854: "asian handicap",
    17: "total goals/points",
    15: "team 1 total",
    62: "team 2 total",
    109: "set handicap (tennis)",
    7099: "set handicap (table tennis)",
    182: "total sets (tennis)",
    2604: "total sets (table tennis)",
}

FOOTBALL, ICE_HOCKEY, BASKETBALL, TENNIS, TABLE_TENNIS = 1, 2, 3, 4, 10


def S(name, direction, status, source=""):
    return {"signal": name, "direction": direction, "status": status, "source": source}


# --- FOOTBALL ---------------------------------------------------------------
# The only sport with a fitted model today, so it is also the only one with `live` signals.
_FOOTBALL = {
    1: [   # 1X2
        S("elo_rating", "higher rating -> higher win probability for that side",
          "live", "football-data.co.uk, 63409 matches over 39 divisions"),
        S("home_advantage", "home side gains a fitted Elo bonus before the comparison",
          "live", "fitted jointly with the ratings"),
        S("goal_supremacy", "Elo difference maps to expected goal margin by a per-league fit",
          "live", "least squares per division"),
        S("xg / xga", "expected goals separate luck from finishing; corrects a hot streak",
          "available", "understat / fbref — licence and robots need checking first"),
        S("injuries_suspensions", "a missing key player lowers that side's effective rating",
          "missing", "no free structured feed found for most leagues"),
        S("rest_days", "short turnaround lowers the affected side",
          "available", "derivable from our own fixture history once it accumulates"),
    ],
    8: [   # double chance
        S("elo_rating", "same direction as 1X2, but the draw is folded IN rather than against",
          "live", "as above"),
        S("draw_propensity", "leagues differ sharply and it is fitted per division; a "
                             "high-draw league makes 'does not lose' cheaper in real terms",
          "live", "observed draw rate 21.1%-32.8% across divisions"),
    ],
    2: [   # handicap
        S("goal_supremacy", "the fitted expected margin IS the handicap's centre",
          "live", "per-division fit"),
        S("scoreline_distribution", "the spread around that margin decides which line is safe",
          "live", "Poisson pair with a fitted draw correction"),
        S("clean_sheet_rate", "a side that concedes rarely narrows the loss tail",
          "available", "computable from the same CSVs, not yet extracted"),
    ],
    17: [  # totals
        S("league_mean_goals", "the league's own scoring level sets the baseline",
          "live", "fitted per division, 2.37-3.18 goals"),
        S("goal_supremacy", "a lopsided match raises the total; an even one lowers it",
          "live", "per-division fit"),
        S("shots_on_target", "combined rate leads goals and is more stable game to game",
          "available", "already in the main-division CSVs (HST/AST), not yet used"),
        S("both_teams_scoring_rate", "drives the low end of the totals ladder",
          "available", "computable from the CSVs"),
    ],
    15: [  # team totals
        S("team_attack_strength", "that side's own scoring rate against this opposition",
          "live", "the Poisson mean for that side"),
        S("opponent_defence", "the other side's concession rate scales it",
          "live", "same"),
    ],
}

# --- SPORTS WITH NO MODEL YET ----------------------------------------------
# Recorded so the gap is explicit. Everything here is why those sports produce no
# selections: the signals are known and the sources are mostly verified, but nothing is
# wired, so the analysis has no direction to give the ladder.
_TABLE_TENNIS = {
    1: [
        S("rating_sc", "the circuit's own player rating; higher rating -> higher win probability",
          "available", "Setka API /Players/{lang}/rating, 2947 players, keyless"),
        S("career_win_rate", "sanity check on the rating and a prior for thin profiles",
          "available", "same endpoint carries win/lost/totalMatches"),
        S("recent_form", "these circuits play many matches a day; short-window form matters",
          "available", "derivable once the results collector has accumulated enough"),
        S("session_fatigue", "players contest several matches per session; late-session "
                             "matches favour the fresher player",
          "available", "computable from match start times we already collect"),
    ],
    7099: [
        S("rating_gap", "a wide gap raises the chance of a straight-sets win, which is what "
                        "decides whether +1.5 or +2.5 sets is the safe rung",
          "available", "Setka ratings + our accumulating set scores"),
        S("set_score_distribution", "the 3-0/3-1/3-2 split IS the set-handicap market",
          "available", "our collector stores per-set scores already"),
    ],
}

_TENNIS = {
    1: [
        S("elo_by_surface", "surface-specific rating; a clay rating misprices a hard court",
          "missing", "Sackmann's archive is CC BY-NC-SA — non-commercial only"),
        S("serve_hold_rate", "the base rate almost everything in tennis derives from",
          "missing", "same licence constraint"),
    ],
}

_BY_SPORT = {
    FOOTBALL: _FOOTBALL,
    TABLE_TENNIS: _TABLE_TENNIS,
    TENNIS: _TENNIS,
}


def for_market(sport_id, group):
    """Signals that inform one market, most-wired first."""
    return sorted(_BY_SPORT.get(sport_id, {}).get(group, []),
                  key=lambda s: {"live": 0, "available": 1, "missing": 2}[s["status"]])


def coverage(sport_id=None):
    """How much of the identified signal set the analysis actually uses.

    This is the number that says how far the product is from its own research, and it is
    deliberately computed rather than asserted.
    """
    out = {}
    sports = [sport_id] if sport_id else list(_BY_SPORT)
    for sid in sports:
        counts = {"live": 0, "available": 0, "missing": 0}
        for group, sigs in _BY_SPORT.get(sid, {}).items():
            for s in sigs:
                counts[s["status"]] += 1
        total = sum(counts.values())
        out[sid] = {**counts, "total": total,
                    "live_pct": round(100.0 * counts["live"] / total, 1) if total else 0.0}
    return out
