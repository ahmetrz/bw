"""What a Betwinner selection actually means when it settles.

A prediction app that shows a price without saying what settles it is lying by omission.
"Over 5.5" on a hockey game is a different bet depending on whether overtime counts, and
"does not lose" on a football knockout is a 90-minute bet even though the tie continues.
This module attaches that meaning, drawn from research/rules/, to every row the app emits.

Scope values:
  regulation      settles on regular time only (football 90'+stoppage; hockey/basketball
                  three-way; the safe default for a 1xBet-family total/handicap whose
                  label does not say otherwise)
  includes_ot     settles after overtime / shootout (basketball & hockey moneyline)
  match           settles on the completed match (tennis, table tennis)
  unknown         we have not confirmed the scope for this market on Betwinner — the app
                  must say so rather than guess

Every entry that depends on a Betwinner term we have NOT read carries needs_confirmation,
so the app can show a caveat instead of a false certainty. See CLAUDE.md hard rule 5 in
spirit: never present unverified settlement as fact.
"""

# Per (sport_id, market group) -> settlement metadata. Groups match engine.bwfeed ids.
# Only the groups the scanner and ladder actually surface are covered; anything else
# resolves to unknown, which is honest rather than wrong.

FOOTBALL = 1
BASKETBALL = 3
TENNIS = 4
ICE_HOCKEY = 2
TABLE_TENNIS = 10

_RULES = {
    FOOTBALL: {
        "scope": "regulation",
        "detail": "90 minutes plus stoppage. Extra time and penalties do NOT count.",
        "by_group": {
            1: "1X2 settles at 90'. In a knockout, the tie may continue but this bet is decided at 90'.",
            8: "Double chance settles at 90'. 'Does not lose' WINS even if the team loses in extra time.",
            2: "Handicap settles at 90', extra time excluded.",
            17: "Total goals settles at 90'. Penalty-shootout goals never count.",
        },
        "needs_confirmation": False,
    },
    BASKETBALL: {
        "scope": "includes_ot",
        "detail": "Moneyline, handicap and totals include overtime; quarter/half markets do not.",
        "by_group": {
            101: "Two-way moneyline. Includes overtime, so there is no draw.",
            2: "Handicap on the full game, overtime included.",
            17: "Total points on the full game, overtime included.",
        },
        # 1xBet-family books usually include OT on full-game basketball, but the label
        # must be read before this is stated as fact.
        "needs_confirmation": True,
    },
    TENNIS: {
        "scope": "match",
        "detail": "Settles on the completed match. Retirement VOIDS set-handicap, totals and correct-score unless already decided.",
        "by_group": {
            1: "Match winner. Two-way — tennis has no draw.",
            109: "SET handicap. In a best-of-3, +1.5 sets loses only to an 0-2 defeat, so it is the 'wins a set' bet.",
            2: "GAME handicap, not sets. The line counts games.",
            17: "Total GAMES, not sets.",
            182: "Total SETS.",
        },
        "needs_confirmation": True,
    },
    ICE_HOCKEY: {
        "scope": "unknown",
        "detail": ("1xBet-family trap: totals and handicaps frequently default to REGULATION "
                   "time unless the label says 'incl. OT'. Moneyline includes OT/shootout; the "
                   "three-way is regulation. The same 'Over 5.5' can be two different bets."),
        # Confirmed on a real NHL payload: the feed carries BOTH markets on the same game.
        # Group 1 priced 1 / X / 2 at 2.357 / 4.315 / 2.667 — a draw is a live outcome, so
        # it settles at 60 minutes. Group 101 priced two ways at 1.853 / 2.035 with no draw
        # available, which is only possible once overtime and the shootout decide it. Both
        # carried the same 3.1% hold, so nothing but the outcome count distinguishes them
        # in the raw feed. A ladder that walked from one to the other would silently change
        # what the bet settles on.
        "by_group": {
            1: "Three-way result, settles at the end of REGULATION (60 minutes). A draw is a real outcome.",
            101: "Two-way moneyline, INCLUDES overtime and the shootout. No draw. Same game as the three-way, different bet.",
            8: "Double chance on the REGULATION three-way — 'does not lose' means not losing after 60 minutes.",
            2: "Handicap. Scope NOT confirmed on Betwinner: this family often settles hockey handicaps on regulation.",
            17: "Total goals. Scope NOT confirmed on Betwinner: may exclude overtime.",
        },
        "needs_confirmation": True,
    },
    TABLE_TENNIS: {
        "scope": "match",
        "detail": ("Settles on the completed match. Format (Bo5 vs Bo7) must be read PER MATCH — "
                   "playoffs switch to Bo7. Retirement voids undetermined markets."),
        "by_group": {
            1: "Match winner. Two-way — no draw.",
            7099: "SET handicap. Over best-of-5 the 'wins a set' rung is +2.5; +1.5 means winning at least two.",
            2: "POINT handicap, not sets. The line counts points.",
            17: "Total POINTS, not sets.",
            2604: "Total SETS.",
        },
        "needs_confirmation": True,
    },
}


def describe(row):
    """Settlement metadata for one row: {scope, detail, needs_confirmation}.

    Rows for sports we have not researched return scope 'unknown' with needs_confirmation
    set, so the caller shows a caveat rather than implying a settlement it cannot back up.
    """
    sport = row.get("sport_id")
    spec = _RULES.get(sport)
    if not spec:
        return {
            "scope": "unknown",
            "detail": "Settlement rules for this sport are not yet documented; treat with caution.",
            "needs_confirmation": True,
            "key": "unknown",
        }

    try:
        group = int(str(row["market_key"][1]).split("|", 1)[0])
    except (KeyError, ValueError, TypeError, IndexError):
        group = None

    by_group = spec["by_group"] or {}
    detail = by_group.get(group, spec["detail"])
    # Stable identifier for the exact rule that was applied, so a presentation layer can
    # localize it without re-deriving the lookup or string-matching the English text.
    key = f"{sport}.{group}" if group in by_group else f"{sport}.*"
    return {
        "scope": spec["scope"],
        "detail": detail,
        "needs_confirmation": spec["needs_confirmation"],
        "key": key,
    }


def annotate(rows):
    """Attach a `settlement` dict to every row, in place. Returns the rows."""
    for r in rows:
        r["settlement"] = describe(r)
    return rows


# Standing list of Betwinner terms that must be read before the app states settlement as
# fact. Surfaced in PRODUCT_STATUS.md and shown to the operator, not silently assumed.
OPEN_QUESTIONS = [
    "Do Betwinner totals/handicaps on ICE HOCKEY include overtime, or default to regulation?",
    "Betwinner's abandonment rule: do decided markets stand (Convention A) or all void (Convention B)?",
    "Betwinner's retirement rule in tennis/table tennis: which of the three conventions?",
    "Betwinner's per-slip payout cap and maximum number of legs.",
    "Betwinner's postponement window (12h / 24h / 48h?).",
]
