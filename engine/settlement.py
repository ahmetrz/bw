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
        "by_group": {},
        # 1xBet-family books usually include OT on full-game basketball, but the label
        # must be read before this is stated as fact.
        "needs_confirmation": True,
    },
    TENNIS: {
        "scope": "match",
        "detail": "Settles on the completed match. Retirement VOIDS set-handicap, totals and correct-score unless already decided.",
        "by_group": {},
        "needs_confirmation": True,
    },
    ICE_HOCKEY: {
        "scope": "unknown",
        "detail": ("1xBet-family trap: totals and handicaps frequently default to REGULATION "
                   "time unless the label says 'incl. OT'. Moneyline includes OT/shootout; the "
                   "three-way is regulation. The same 'Over 5.5' can be two different bets."),
        "by_group": {},
        "needs_confirmation": True,
    },
    TABLE_TENNIS: {
        "scope": "match",
        "detail": ("Settles on the completed match. Format (Bo5 vs Bo7) must be read PER MATCH — "
                   "playoffs switch to Bo7. Retirement voids undetermined markets."),
        "by_group": {},
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
        }

    try:
        group = int(str(row["market_key"][1]).split("|", 1)[0])
    except (KeyError, ValueError, TypeError, IndexError):
        group = None

    detail = spec["by_group"].get(group, spec["detail"]) if spec["by_group"] else spec["detail"]
    return {
        "scope": spec["scope"],
        "detail": detail,
        "needs_confirmation": spec["needs_confirmation"],
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
