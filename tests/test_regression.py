"""Regression anchor: re-run fixtures/sample.json and assert the table has not moved.

Standard library only — the project takes no pip dependencies.

    python -m unittest discover -s tests -v

The snapshot lives in fixtures/expected_report.json. Regenerate deliberately, never
casually, and read the diff before you do:

    python tests/test_regression.py --update
"""
import collections
import json
import os
import re
import tempfile
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from engine import (bwfeed, grade, ladder, mirror, model_generic,  # noqa: E402
                    parlay, pick, rating, results_store, score, settlement, signals,
                    simulated, telegram)
from tools import collect_live, daily_report, fetch_window  # noqa: E402
from tools import grade_predictions  # noqa: E402
from tools import daily_results as tools_daily_results  # noqa: E402
from tools import make_method_page, make_picks_page  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tools"))
import grade_predictions  # noqa: E402

SAMPLE = os.path.join(ROOT, "fixtures", "sample.json")
SNAPSHOT = os.path.join(ROOT, "fixtures", "expected_report.json")


def _sample():
    with open(SAMPLE) as f:
        return json.load(f)

# Every field CLAUDE.md hard rule 1 requires on an emitted selection.
REQUIRED_FIELDS = {
    "odds", "implied_prob", "market_overround", "margin_score", "limit_score",
    "range_score", "total_score", "limit", "staleness_seconds", "market_type",
    "main_line", "flags",
}


def build_report():
    """Run the real pipeline and return exactly what report.write_json would emit."""
    with open(SAMPLE) as f:
        data = json.load(f)
    rows = score.filter_and_score(bwfeed.normalize(data))
    out = []
    for r in rows[: config.TOP_N]:
        out.append({
            "fixture_id": r["fixture_id"],
            "match": f"{r['p1']} v {r['p2']}",
            "start": r["start"],
            "market_type": r["market_type"],
            "main_line": r["main_line"],
            "selection": r["selection"],
            "odds": r["odds"],
            "implied_prob": round(r["implied"], 4),
            "market_overround": round(r["overround"], 4),
            "limit": r["limit"],
            "staleness_seconds": r["staleness_seconds"],
            "margin_score": r["margin_score"],
            "limit_score": r["limit_score"],
            "range_score": r["range_score"],
            "total_score": r["total_score"],
            "flags": r["flags"],
        })
    return out


class TestRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual = build_report()
        with open(SNAPSHOT) as f:
            cls.expected = json.load(f)

    def test_row_count_unchanged(self):
        self.assertEqual(len(self.actual), len(self.expected))

    def test_table_unchanged(self):
        for i, (a, e) in enumerate(zip(self.actual, self.expected)):
            self.assertEqual(a, e, f"row {i + 1} changed:\n  got      {a}\n  expected {e}")

    def test_hard_rule_1_every_row_carries_every_field(self):
        for i, row in enumerate(self.actual):
            missing = REQUIRED_FIELDS - set(row)
            self.assertFalse(missing, f"row {i + 1} is missing {sorted(missing)}")

    def test_suppress_alt_lines_when_main_line_exists(self):
        """SUPPRESS rule 2 — no alternative line may be emitted in a default scan."""
        self.assertFalse(config.INCLUDE_ALT_LINES, "fixture assumes a main-line-only scan")
        for i, row in enumerate(self.actual):
            self.assertNotIn("alt_line", row["flags"], f"row {i + 1} is an alt line")

    def test_no_placeholder_fixtures(self):
        """Betwinner's feed carries 'Home v Away' template entries; they priced at the
        lowest hold in the pull and took the entire top 24 before being suppressed."""
        for row in self.actual:
            self.assertNotEqual(row["match"], "Home v Away")

    def test_scores_actually_discriminate(self):
        """Guards the normalization bug: scaling the hold against a row-weighted max
        squeezed every ordinary market into 0.95-1.00 and printed 1.000 for everything."""
        scores = {r["total_score"] for r in self.actual}
        self.assertGreater(len(scores), 5, f"only {len(scores)} distinct scores — flat again")

    def test_more_than_one_market_type(self):
        """CLAUDE.md's first-run sanity check: a table that is all one market type is a
        red flag. It was 100% totals under every weighting tried, because one global
        hold scale ranked every totals market above every 1X2. Scaling within each type
        is what fixed it, and this is what would catch that regressing."""
        types = collections.Counter(r["market_type"] for r in self.actual)
        self.assertGreater(len(types), 1, f"top-N is a single market type: {dict(types)}")

    def test_more_than_one_fixture(self):
        """The other half of that check — one cheap fixture must not fill the table."""
        fixtures = collections.Counter(r["fixture_id"] for r in self.actual)
        self.assertGreater(len(fixtures), 1, "top-N came from a single fixture")

    def test_cap_counts_matches_not_game_ids(self):
        """A fixture and its halves are three game ids for ONE match. Capping on the
        game id let a single match take 6 of 50 rows — CSKA Sofia v Spartak Trnava did
        exactly that — because each id got its own allowance. The cap has to bind on
        the match, which is what a reader of the table sees."""
        cap = getattr(config, "MAX_PER_FIXTURE", 0)
        if not cap:
            self.skipTest("cap disabled")
        worst = collections.Counter(r["match"] for r in self.actual).most_common(1)[0]
        self.assertLessEqual(worst[1], cap, f"match {worst[0]!r} took {worst[1]} rows")

    def test_ranked_descending(self):
        s = [r["total_score"] for r in self.actual]
        self.assertEqual(s, sorted(s, reverse=True))

    def test_settlement_is_stated_for_football(self):
        """A prediction app must say what a bet means. Football settlement is confirmed
        (90 minutes), so every football row must carry a settlement scope of 'regulation'
        and must NOT be flagged as needing confirmation."""
        with open(SAMPLE) as f:
            rows = score.filter_and_score(bwfeed.normalize(json.load(f)))
        settlement.annotate(rows)
        football = [r for r in rows if r.get("sport_id") == 1]
        self.assertTrue(football, "sample should contain football rows")
        for r in football:
            s = r["settlement"]
            self.assertEqual(s["scope"], "regulation")
            self.assertFalse(s["needs_confirmation"], "football settlement is confirmed")

    def test_double_chance_is_scored_not_discarded(self):
        """Double chance covers the three-way outcome space TWICE — 1X, 12 and X2 each
        contain two of the three results — so its implied probabilities sum to about 2.
        Read as a hold that meant 100%+, and MAX_OVERROUND then dropped every one of
        them. That silently removed the top rung of the football safety ladder from the
        scan: the operator's rule is to take 'does not lose' over the outright win, and
        there was no 'does not lose' left to take."""
        rows = score.filter_and_score(bwfeed.normalize(_sample()))
        dc = [r for r in rows if r["market_type"] == "doubleChance"]
        self.assertTrue(dc, "no double-chance rows survived scoring")
        worst = max(r["overround"] for r in dc)
        self.assertLess(worst, 0.25, f"double-chance hold computed as {worst:.1%} — coverage lost")

    def test_handicap_markets_have_both_sides(self):
        """A handicap is quoted as home -1.5 against away +1.5, so the two halves of one
        market carry OPPOSITE signed lines. Keying the market on the raw line split every
        handicap into two one-sided markets: the football holds ran 0.230 to 1.961 instead
        of clustering just above 1, and in basketball every handicap was a lone selection
        and got dropped for want of a second side."""
        counts = collections.Counter()
        for r in bwfeed.normalize(_sample()):
            if r["market_type"] == "spreads":
                counts[r["market_key"]] += 1
        self.assertTrue(counts, "sample should contain handicap markets")
        singles = [k for k, n in counts.items() if n != 2]
        self.assertFalse(singles, f"{len(singles)} handicap markets are not two-sided")

    def test_ladder_is_ordered_from_riskiest_to_safest(self):
        """The ladder's whole contract is that each rung wins in strictly more states than
        the one above, so `safest` can just take the last rung that clears the gate. If the
        ordering is wrong that call returns a riskier bet while claiming it is safer.

        Double chance IS a +0.5 handicap — 'home or draw' wins exactly where home +0.5 wins
        — so it has to be ranked on the same goal scale as the handicaps. Ranked as its own
        tier above them, the ladder preferred an Asian +0.25, which refunds only half the
        stake on a draw where double chance pays in full."""
        rows = [r for r in bwfeed.normalize(_sample()) if not r.get("sub_game")]
        by_fixture = collections.defaultdict(list)
        for r in rows:
            by_fixture[r["fixture_id"]].append(r)

        checked = 0
        for fixture_rows in by_fixture.values():
            for side in ("home", "away"):
                rungs = ladder.build(fixture_rows, 1, side)
                if len(rungs) < 3:
                    continue
                checked += 1
                ranks = [x["rank"] for x in rungs]
                self.assertEqual(ranks, sorted(ranks), "ladder is not rank-ordered")
                dc = [x for x in rungs if "does not lose" == x["label"].split(side + " ")[-1]]
                if dc:
                    self.assertEqual(dc[0]["rank"], 0.5,
                                     "double chance must rank as the +0.5 handicap it is")
                # Safety has a price, so the ladder should trend downward in odds. It is
                # not STRICTLY monotonic and must not be asserted as such: a whole-number
                # handicap refunds the stake on an exact N-goal loss, so +1 prices shorter
                # than the +1.5 above it (measured 1.013 against 1.030). Those push-driven
                # inversions are a couple of percent. A sign error is not — reading the
                # away side's handicap off the home-perspective line offered "away +2" at
                # 4.20 against an away moneyline of 2.04, a supposedly safer rung at more
                # than twice the price.
                odds = [x["row"]["odds"] for x in rungs]
                self.assertLessEqual(odds[-1], odds[0],
                                     f"safest rung costs more than the riskiest: {list(zip(ranks, odds))}")
                for (r1, o1), (r2, o2) in zip(zip(ranks, odds), list(zip(ranks, odds))[1:]):
                    self.assertLessEqual(
                        o2, o1 * 1.10,
                        f"rung {r2} is {o2 / o1 - 1:.0%} dearer than {r1} — wrong side of the line?")
        self.assertGreater(checked, 5, "not enough fixtures carried a full ladder to test")

    def test_excluded_sports_never_reach_the_ranking(self):
        """RNG markets are the cheapest on the book, so the scorer would rank them first.

        Betwinner's lottery markets measured a 3.09% median hold against football's 8.65%
        — roughly three times cheaper than real sport. Since margin_score rewards a low
        hold, a sweep that included them would be headed by lottery tickets, and no data
        could ever justify one: past draws say nothing about the next, and the book can
        compute the exact odds as well as we can.

        Synthesises rows rather than requiring a live pull, so the guard holds offline.
        """
        excluded = getattr(config, "EXCLUDED_SPORTS", set())
        self.assertTrue(excluded, "no sports are excluded — the RNG guard is off")

        with open(SAMPLE) as f:
            rows = bwfeed.normalize(json.load(f))
        victim = sorted(excluded)[0]
        # Copy real rows onto an excluded sport and make them the cheapest thing present,
        # so they would sweep the table if the filter were not applied.
        planted = []
        for r in rows[:200]:
            p = dict(r)
            p["sport_id"] = victim
            p["fixture_id"] = -abs(p["fixture_id"])
            p["match_id"] = p["fixture_id"]
            p["market_key"] = (p["fixture_id"], p["market_key"][1])
            p["odds"] = 2.0
            p["implied"] = 0.5      # two of these per market sum to 1.0 -> a 0% hold
            planted.append(p)

        scored = score.filter_and_score(rows + planted)
        leaked = [r for r in scored if r.get("sport_id") in excluded]
        self.assertFalse(leaked, f"{len(leaked)} rows from an excluded sport reached the ranking")

    def test_outrights_are_suppressed(self):
        """An entry with no second participant is not a head-to-head, and must not parse.

        The feed uses an empty O2 for tournament winners, election questions, novelty
        bundles that appear even inside football, and multi-runner races. All of them
        break the machinery downstream: the parlay's one-selection-per-match rule has
        nothing to bind on, and the safety ladder has no two-outcome market to walk down.

        They are also the long-dated bets, and crucially the start timestamp does not say
        so — the 2026 Senate markets are stamped 5 to 16 days out because that is when the
        line runs, not when the seat is decided. A horizon filter would miss them entirely,
        which is why this is keyed on the missing opponent instead.
        """
        with open(SAMPLE) as f:
            data = json.load(f)
        base = len(bwfeed.normalize(data))
        self.assertGreater(base, 0, "sample should normalize to something")

        outright = dict(data[0])
        outright["O2"] = ""
        outright["O1"] = "Some Tournament. 2026. Winner"
        outright["CI"] = -999
        blank = dict(data[0])
        blank["O2"] = "   "
        blank["CI"] = -998

        rows = bwfeed.normalize(data + [outright, blank])
        self.assertEqual(len(rows), base, "an entry without an opponent reached the rows")
        self.assertFalse([r for r in rows if r["fixture_id"] in (-999, -998)])

    def test_picks_clear_both_gates(self):
        """Every offered selection must clear the odds gate AND the model's confidence floor.

        Synthetic probabilities, so this never touches the network. The model is told the
        home side is strong, which is the only thing allowed to set the direction — the
        prices are not consulted for that and must not be.
        """
        probs = {
            "p_home": 0.62, "p_draw": 0.23, "p_away": 0.15,
            "p_over": {0.5: 0.95, 1.5: 0.78, 2.5: 0.52, 3.5: 0.28, 4.5: 0.13, 5.5: 0.05},
            "gd": {-3: 0.02, -2: 0.05, -1: 0.08, 0: 0.23, 1: 0.30, 2: 0.20, 3: 0.12},
            "score_mass": 1.0,
        }
        rows = [r for r in bwfeed.normalize(_sample()) if not r.get("sub_game")]
        by_match = collections.defaultdict(list)
        for r in rows:
            by_match[r.get("match_id", r["fixture_id"])].append(r)

        checked = 0
        for match_rows in by_match.values():
            got = pick.best(match_rows, 1, probs)
            if not got:
                continue
            checked += 1
            self.assertGreaterEqual(got["odds"], config.MIN_ODDS,
                                    f"{got['ladder_rung']} priced below the gate")
            self.assertGreaterEqual(got["model_survival"], config.MIN_MODEL_SURVIVAL,
                                    f"{got['ladder_rung']} below the confidence floor")
        self.assertGreater(checked, 3, "not enough matches produced a pick to test")

    def test_pick_takes_the_safest_qualifying_rung(self):
        """The ladder must not be short-circuited by a better price further up.

        This is the operator's rule in its sharpest form: given two rungs that both clear
        the gates, the SAFER one wins even though it pays less. A selector that maximised
        odds — or that read a short price as a high probability — would invert this.
        """
        probs = {
            "p_home": 0.55, "p_draw": 0.25, "p_away": 0.20,
            "p_over": {0.5: 0.94, 1.5: 0.75, 2.5: 0.48, 3.5: 0.25, 4.5: 0.11, 5.5: 0.04},
            "gd": {-3: 0.03, -2: 0.06, -1: 0.11, 0: 0.25, 1: 0.28, 2: 0.17, 3: 0.10},
            "score_mass": 1.0,
        }
        rows = [r for r in bwfeed.normalize(_sample()) if not r.get("sub_game")]
        by_match = collections.defaultdict(list)
        for r in rows:
            by_match[r.get("match_id", r["fixture_id"])].append(r)

        compared = 0
        for match_rows in by_match.values():
            for direction in ("home", "away"):
                rungs = ladder.build(match_rows, 1, direction)
                # Mirrors every gate the picker applies, including the push exclusion —
                # otherwise this test expects a rung the picker is right to refuse.
                allow_push = getattr(config, "ALLOW_PUSH_MARKETS", True)
                qualifying = [
                    x for x in rungs
                    if x["row"]["odds"] >= config.MIN_ODDS
                    and (allow_push or not pick._can_push(x["row"]))
                    and (pick._survival(x["row"], probs) or 0) >= config.MIN_MODEL_SURVIVAL
                ]
                if len(qualifying) < 2:
                    continue
                chosen = max(qualifying, key=lambda x: x["rank"])
                cands = pick.candidates(match_rows, 1, probs)
                mine = [c for c in cands if c.get("direction") == direction]
                if not mine:
                    continue
                compared += 1
                self.assertEqual(
                    mine[0]["ladder_rung"], chosen["label"],
                    "picked a rung that is not the safest qualifying one")
        self.assertGreater(compared, 0, "no match offered two qualifying rungs to compare")

    def test_telegram_chunks_stay_under_the_limit(self):
        """Telegram rejects anything over 4096 characters, and a rejected send is a
        silently missing report."""
        text = "\n".join(f"satır {i} — bir seçim daha" for i in range(2000))
        parts = telegram.chunks(text)
        self.assertTrue(parts)
        for p in parts:
            self.assertLessEqual(len(p), telegram.MAX_LEN)
        # Nothing may be dropped on the way through.
        self.assertEqual(sum(len(p) for p in parts) + len(parts) - 1, len(text))

    def test_grader_settles_every_ladder_market(self):
        """The grader is what makes everything else falsifiable, so its arithmetic is
        pinned case by case.

        The push cases matter most. A grader that scores a returned stake as a loss makes
        whole-number handicaps look worse than they are, and the next round of
        "improvements" would then strip the safest rungs out of the ladder — the
        measurement would quietly destroy the thing it is measuring.

        Scores are written home-first and the direction is stated in the label, because
        getting that backwards is exactly the mistake these cases were written to catch.
        """
        def row(group, oid, line):
            return {"market_key": (1, f"{group}|{line}"), "outcome_id": oid}

        cases = [
            ("1X2 home, home wins 2-1", row(1, 1, "None"), 2, 1, grade.WIN),
            ("1X2 home, drawn 1-1", row(1, 1, "None"), 1, 1, grade.LOSS),
            ("DC 1X, drawn 1-1", row(8, 4, "None"), 1, 1, grade.WIN),
            ("DC X2, home wins 2-0", row(8, 6, "None"), 2, 0, grade.LOSS),
            ("away +1.5, away loses by 2", row(2, 8, "-1.5"), 2, 0, grade.LOSS),
            ("away +1.5, away loses by 1", row(2, 8, "-1.5"), 1, 0, grade.WIN),
            ("away +1, away loses by exactly 1", row(2, 8, "-1"), 1, 0, grade.PUSH),
            ("away +1, away loses by 2", row(2, 8, "-1"), 2, 0, grade.LOSS),
            ("home +2.5, home loses by 2", row(2, 7, "2.5"), 0, 2, grade.WIN),
            ("home +2.5, home loses by 3", row(2, 7, "2.5"), 0, 3, grade.LOSS),
            ("home +0.25, drawn 1-1", row(2, 7, "0.25"), 1, 1, grade.HALF),
            ("home +0.25, home loses 0-1", row(2, 7, "0.25"), 0, 1, grade.LOSS),
            ("over 2.5, 2-1", row(17, 9, "2.5"), 2, 1, grade.WIN),
            ("under 2.5, 2-1", row(17, 10, "2.5"), 2, 1, grade.LOSS),
            ("over 3.0 exact, 2-1", row(17, 9, "3.0"), 2, 1, grade.PUSH),
            # A HANDICAP IN SETS IS STILL A HANDICAP, and for a long time this grader did
            # not know it. Group 7099 is the safety ladder's favourite table tennis rung
            # and table tennis was the second most-predicted sport, so every one of those
            # predictions settled as None and sat ungraded for ever. The first real hit
            # rate came back empty and it looked like missing results; the results were in
            # the store the whole time and nothing could score them.
            ("TT +2.5 sets, lost 1-3", row(7099, 5749, "2.5"), 1, 3, grade.WIN),
            ("TT +2.5 sets, lost 0-3", row(7099, 5749, "2.5"), 0, 3, grade.LOSS),
            ("TT away +1.5 sets, away won 3-1", row(7099, 5750, "-1.5"), 1, 3, grade.WIN),
            # A best-of-three whitewash beats a +1.5 set handicap and clears +2.5. Both
            # sides of that boundary, because a set handicap is the tennis and table
            # tennis ladder's whole vocabulary.
            ("tennis +1.5 sets, lost 0-2", row(109, 732, "1.5"), 0, 2, grade.LOSS),
            ("tennis +2.5 sets, lost 0-2", row(109, 732, "2.5"), 0, 2, grade.WIN),
            ("tennis +1.5 sets, lost 1-2", row(109, 732, "1.5"), 1, 2, grade.WIN),
            ("TT total sets over 3.5, 3-2", row(2604, 3150, "3.5"), 3, 2, grade.WIN),
            ("tennis total sets under 3.5, 2-0", row(182, 972, "3.5"), 2, 0, grade.WIN),
            ("snooker total frames over 8.5, 5-4", row(876, 1850, "8.5"), 5, 4, grade.WIN),
            ("esports map handicap +1.5, lost 1-2", row(2438, 2826, "1.5"), 1, 2, grade.WIN),
            ("esports total maps under 2.5, 2-0", row(2436, 2825, "2.5"), 2, 0, grade.WIN),
            ("team 1 total over 1.5, 2-0", row(15, 11, "1.5"), 2, 0, grade.WIN),
            ("team 2 total under 1.5, 2-0", row(62, 14, "1.5"), 2, 0, grade.WIN),
            ("team 2 total over 1.5, 2-2", row(62, 13, "1.5"), 2, 2, grade.WIN),
        ]
        for label, r, hg, ag, expected in cases:
            self.assertEqual(grade.settle(r, hg, ag), expected, label)

        # Every market the LADDER can select must be settleable. A rung that cannot be
        # graded is a prediction that never enters the hit rate, which is worse than not
        # offering it: the model looks untested rather than wrong.
        settleable = (set(grade.HANDICAP_GROUPS) | set(grade.TOTAL_GROUPS)
                      | set(grade.TEAM_TOTAL_GROUPS) | {1, 8, 101})
        for group in ladder.LADDER_GROUPS:
            self.assertIn(group, settleable,
                          f"ladder can select group {group} and the grader cannot score it")

    def test_grader_leaves_unknown_markets_ungraded(self):
        """A market the grader does not understand must return None, not a verdict.

        Scoring a market on a guess is worse than not scoring it: it puts a fabricated
        number into the hit rate that every later decision is steered by."""
        unknown = {"market_key": (1, "9999|None"), "outcome_id": 12345}
        self.assertIsNone(grade.settle(unknown, 2, 1))

    def test_push_is_neither_a_win_nor_a_loss(self):
        """A returned stake must not be counted in either column."""
        s = grade.summarize([
            {"result": grade.WIN, "odds": 2.0},
            {"result": grade.PUSH, "odds": 1.5},
            {"result": grade.LOSS, "odds": 1.8},
        ])
        self.assertEqual((s["win"], s["push"], s["loss"]), (1, 1, 1))
        # Hit rate is over DECIDED legs, so the push is excluded from the denominator.
        self.assertAlmostEqual(s["hit_rate"], 0.5)
        # Staked 3, returned 2.0 (win) + 1.0 (push) + 0 = 3.0 -> break even.
        self.assertAlmostEqual(s["returned"], 3.0)
        self.assertAlmostEqual(s["roi_pct"], 0.0)

    def test_grader_will_not_score_an_unplayed_match(self):
        """The grader must key on the DATE, not just on the two teams.

        This is the bug that nearly poisoned the whole measurement. Keyed on teams alone,
        31 predictions whose matches had not yet kicked off came back graded, 87.1% of
        them winners — every one of them settled against an EARLIER meeting of the same
        two sides. A hit rate built that way is worse than no hit rate, because every
        later change would have been steered by it.
        """
        table = {("ilves", "lahti"): [("2026-03-01", 3, 0), ("2026-07-26", 0, 0)]}

        # The earlier meeting must not answer for the later fixture.
        self.assertEqual(
            grade_predictions.lookup_result(table, "Ilves", "Lahti", "2026-07-26T12:00"),
            (0, 0))
        self.assertEqual(
            grade_predictions.lookup_result(table, "Ilves", "Lahti", "2026-03-01T12:00"),
            (3, 0))
        # A fixture with no matching date is ungraded, not graded from a neighbour.
        self.assertIsNone(
            grade_predictions.lookup_result(table, "Ilves", "Lahti", "2026-05-15T12:00"))
        # An unknown pairing stays ungraded.
        self.assertIsNone(
            grade_predictions.lookup_result(table, "Ilves", "Nobody", "2026-07-26T12:00"))

    def test_push_markets_are_excluded_when_disabled(self):
        """With ALLOW_PUSH_MARKETS off, nothing that can return the stake may be offered.

        Three families can push and all three must go: whole-number handicaps (+1 refunds
        on an exact one-goal defeat), quarter handicaps (+0.25 splits the stake so half can
        be returned), and whole-number totals (over 3.0 refunds on exactly three goals).
        Half-lines never can, which is why they are what remains.

        Detection is on the LINE rather than on the model's push probability, because a
        model can put zero mass on the pushing scoreline for one fixture while the market
        still carries the possibility.
        """
        def row(group, line):
            return {"market_key": (1, f"{group}|{line}")}

        for group, line in [(2, "1"), (2, "0.25"), (2, "-2.75"), (2854, "2"),
                            (17, "3.0"), (7099, "2"), (2604, "4")]:
            self.assertTrue(pick._can_push(row(group, line)), f"G{group} {line} can push")
        for group, line in [(2, "1.5"), (2, "-2.5"), (17, "2.5"), (7099, "1.5"),
                            (8, "None"), (1, "None"), (101, "None")]:
            self.assertFalse(pick._can_push(row(group, line)), f"G{group} {line} cannot push")

        if getattr(config, "ALLOW_PUSH_MARKETS", True):
            self.skipTest("push markets are enabled in config")

        probs = {
            "p_home": 0.55, "p_draw": 0.25, "p_away": 0.20,
            "p_over": {0.5: 0.94, 1.5: 0.75, 2.5: 0.48, 3.5: 0.25, 4.5: 0.11, 5.5: 0.04},
            "gd": {-3: 0.03, -2: 0.06, -1: 0.11, 0: 0.25, 1: 0.28, 2: 0.17, 3: 0.10},
            "score_mass": 1.0,
        }
        rows = [r for r in bwfeed.normalize(_sample()) if not r.get("sub_game")]
        by_match = collections.defaultdict(list)
        for r in rows:
            by_match[r.get("match_id", r["fixture_id"])].append(r)

        offered = 0
        for match_rows in by_match.values():
            for got in pick.candidates(match_rows, 1, probs):
                offered += 1
                self.assertFalse(pick._can_push(got),
                                 f"offered a pushable market: {got.get('ladder_rung')}")
                self.assertEqual(got.get("model_push"), 0.0,
                                 f"offered a leg with push mass: {got.get('ladder_rung')}")
        self.assertGreater(offered, 5, "not enough selections produced to test")

    def test_links_are_built_on_the_resolved_mirror(self):
        """Links must use the host that is currently reachable, not a hardcoded one.

        The book is blocked in Turkey and rotates its public domain, so a fixed host
        produces links that quietly stop opening — the failure is invisible until someone
        taps one. The numeric path is deliberate too: the book redirects it to its own
        slugged form, so the link resolves without us guessing a competition slug.
        """
        row = {"sport_id": 1, "champ_id": 67559, "fixture_id": 354178770}
        self.assertEqual(
            parlay.betwinner_url(row, host="betwinner2.com"),
            "https://betwinner2.com/en/line/1/67559/354178770")
        # A different mirror must change every link, with nothing else hardcoded.
        self.assertEqual(
            parlay.betwinner_url(row, host="example-mirror.com"),
            "https://example-mirror.com/en/line/1/67559/354178770")
        # Missing ids yield no link rather than a broken one.
        self.assertIsNone(parlay.betwinner_url({"sport_id": 1}, host="betwinner2.com"))
        self.assertIsNone(mirror.event_url("betwinner2.com", 1, None, 5))

    def test_book_is_betwinner(self):
        """A direct pull is Betwinner by construction, so the mismatch banner must
        stay silent on this fixture."""
        with open(SAMPLE) as f:
            data = json.load(f)
        self.assertTrue(bwfeed.is_bwfeed(data))
        self.assertIn(config.BOOK, bwfeed.books_in(data))

    def test_score_never_reads_the_price(self):
        """The 0-100 score must be computable without the odds, and blind to them.

        This is hard rule 6 wearing a different hat. A score that folded the price in
        would rank by the book's own opinion while looking like analysis — and it would
        do it silently, because a short price and a confident model agree often enough
        that nobody would notice for weeks.
        """
        base = {"model_survival": 0.90, "name_match": 1.0, "division_matches": 6000}
        want = rating.score(base)["score"]
        for odds in (1.10, 1.85, 4.40, 17.0):
            priced = dict(base, odds=odds, implied_prob=1 / odds, overround=0.07)
            self.assertEqual(rating.score(priced)["score"], want,
                             "the score moved when only the price changed")
        # And it must not be silently derivable from the price either: identical odds
        # with different model confidence have to score differently.
        a = rating.score({"model_survival": 0.99, "name_match": 1.0, "odds": 1.2})
        b = rating.score({"model_survival": 0.76, "name_match": 1.0, "odds": 1.2})
        self.assertGreater(a["score"], b["score"])

    def test_score_reads_as_the_model_probability(self):
        """The score has to mean ONE thing: how often the model thinks this wins.

        The first version scored a position in a band, so a 75.8% selection came out at
        28/100 and was read as "the model is 28% sure" — the opposite of its meaning. With
        full evidence the number must now BE the probability, with nothing to translate.
        """
        floor = config.MIN_MODEL_SURVIVAL
        full = {"name_match": 1.0, "division_matches": 12000}
        for prob in (0.758, 0.83, 0.91, 0.999):
            got = rating.score(dict(full, model_survival=prob), floor)
            self.assertAlmostEqual(got["score"], round(100.0 * prob, 1), places=1)
            self.assertAlmostEqual(got["model_pct"], round(100.0 * prob, 1), places=1)
        # No evidence at all cannot leave a selection worth more than the entry condition.
        none = rating.score({"model_survival": 0.95, "name_match": 0.80}, floor)
        self.assertAlmostEqual(none["score"], 100.0 * floor, places=1)

    def test_evidence_discounts_a_weaker_foundation(self):
        """Same stated probability, different backing — the score has to say so, and say
        how much it cost."""
        strong = rating.score({"model_survival": 0.9, "name_match": 1.0,
                               "division_matches": 12000})
        weak = rating.score({"model_survival": 0.9, "name_match": 0.83,
                             "division_matches": 400})
        self.assertEqual(strong["model_pct"], weak["model_pct"])
        self.assertGreater(strong["evidence_pct"], weak["evidence_pct"])
        self.assertGreater(strong["score"], weak["score"])
        # The discount is visible in the same units as the score, so it can be argued with.
        self.assertAlmostEqual(weak["score"] + weak["evidence_penalty"],
                               strong["score"], places=1)
        self.assertEqual(strong["evidence_penalty"], 0.0)

    def test_score_bands_are_fixed_not_relative(self):
        """A label has to mean the same thing on a strong card and a weak one. Quantile
        bands would relabel the identical bet every morning."""
        self.assertEqual(rating.band(96.0), "çok güçlü")
        self.assertEqual(rating.band(75.4), "sınırda")
        self.assertEqual(rating.score({"model_survival": 0.93, "name_match": 1.0,
                                       "division_matches": 9000})["band"], "çok güçlü")

    def test_numbering_is_best_first_and_shared_across_windows(self):
        """#1 is the day's best selection, and a bet keeps ONE number in both windows.

        Numbering each window separately would put two different bets at #7 on the same
        page, which is worse than no number at all.
        """
        def leg(mid, surv, line):
            return {"match_id": mid, "market_key": ("k", line), "outcome_id": 1,
                    "model_survival": surv, "name_match": 1.0, "division_matches": 9000}

        short = [leg(2, 0.80, "17|2.5"), leg(1, 0.95, "17|5.5")]
        full = [leg(3, 0.88, "8|"), leg(1, 0.95, "17|5.5"), leg(2, 0.80, "17|2.5")]
        results = daily_report.number([
            {"hours": 24, "picks": short}, {"hours": 48, "picks": full},
        ])
        by_hours = {r["hours"]: r["picks"] for r in results}

        self.assertEqual([p["id"] for p in by_hours[48]], [1, 2, 3])
        self.assertEqual([p["match_id"] for p in by_hours[48]], [1, 3, 2])
        # The 24h window inherits the numbers rather than renumbering from 1.
        self.assertEqual({p["match_id"]: p["id"] for p in by_hours[24]}, {1: 1, 2: 3})
        for p in by_hours[24]:
            self.assertEqual(p["score"], next(q["score"] for q in by_hours[48]
                                              if q["match_id"] == p["match_id"]))

    def test_picks_page_renders_every_selection_with_its_link(self):
        """The page IS the deliverable now, so a dropped row is a dropped bet.

        Also asserts the id/score/window data attributes the filters run on: a filter
        reading an attribute that is not there fails silently by showing everything.
        """
        report = {
            "generated": "2026-07-26T06:10:00+00:00", "link_host": "betwinner2.com",
            "min_odds": 1.10, "min_model_survival": 0.75,
            "windows": [
                {"hours": 24, "matches": 3, "skipped": {"no_model": 1},
                 "picks": [{"id": 1, "score": 88.0, "band": "güçlü", "model_pct": 88.0,
                            "evidence_pct": 100.0, "model_survival": 0.88, "p1": "Napoli", "p2": "Carrarese",
                            "league": "Club Friendlies", "start": "2026-07-26T16:00:00+00:00",
                            "sport_id": 1, "selection_tr": "Toplam gol 5.5 altı",
                            "odds": 1.10, "settlement": {"scope": "regulation"},
                            "url": "https://betwinner2.com/en/line/1/1/2"}]},
                {"hours": 48, "matches": 5, "skipped": {"no_model": 2},
                 "picks": [{"id": 1, "score": 88.0, "band": "güçlü", "model_pct": 88.0,
                            "evidence_pct": 100.0, "model_survival": 0.88, "p1": "Napoli", "p2": "Carrarese",
                            "league": "Club Friendlies", "start": "2026-07-26T16:00:00+00:00",
                            "sport_id": 1, "selection_tr": "Toplam gol 5.5 altı",
                            "odds": 1.10, "settlement": {"scope": "regulation"},
                            "url": "https://betwinner2.com/en/line/1/1/2"},
                           {"id": 2, "score": 76.0, "band": "sınırda", "model_pct": 76.0,
                            "evidence_pct": 100.0, "model_survival": 0.76, "p1": "Anna Lapa", "p2": "V. Shevchuk",
                            "league": "Setka Cup", "start": "2026-07-27T09:00:00+00:00",
                            "sport_id": 10, "selection_tr": "Anna Lapa +2.5 set handikap",
                            "odds": 1.24, "settlement": {"scope": "match",
                                                         "needs_confirmation": True},
                            "url": "https://betwinner2.com/en/line/10/3/4"}]},
            ],
        }
        out = os.path.join(ROOT, "fixtures", "_tmp_picks.html")
        try:
            n = make_picks_page.build(report, out)
            with open(out, encoding="utf-8") as f:
                page = f.read()
        finally:
            if os.path.exists(out):
                os.remove(out)

        self.assertEqual(n, 2)
        self.assertEqual(page.count('<tr data-sport='), 2)
        # The 24h pick is tagged with the window it first appears in, so "24 saat" is a
        # real filter rather than a duplicate of the full list.
        self.assertIn('data-window="24"', page)
        self.assertIn('data-window="48"', page)
        for needle in ('data-id="1"', 'data-score="88.0"', 'data-odds="1.24"', 'güçlü',
                       "Napoli - Carrarese", "Masa Tenisi", "Futbol",
                       "https://betwinner2.com/en/line/10/3/4"):
            self.assertIn(needle, page)
        # The count the model could NOT reach is on the page, not quietly left off it.
        self.assertIn("modelsiz 2", page)
        # Self-contained: it is opened from a Telegram attachment, often offline.
        for external in ("http://", "src=", "<link"):
            self.assertNotIn(external, page.replace("https://betwinner2.com", ""))

    def test_picks_page_escapes_hostile_text(self):
        """Team names come from the feed. One containing a quote or a tag must not be
        able to break out of an attribute — the page is opened on the operator's phone."""
        report = {"windows": [{"hours": 48, "matches": 1, "picks": [{
            "id": 1, "score": 50.0, "band": "sınırda", "model_pct": 50.0, "evidence_pct": 1.0,
            "p1": '<script>alert("x")</script>', "p2": 'O"Brien & Sons',
            "league": "<b>x</b>", "start": "2026-07-26T16:00:00+00:00", "sport_id": 1,
            "selection_tr": "5.5 altı", "odds": 1.5, "settlement": {},
            "url": 'https://x.test/"onerror="alert(1)'}]}]}
        out = os.path.join(ROOT, "fixtures", "_tmp_escape.html")
        try:
            make_picks_page.build(report, out)
            with open(out, encoding="utf-8") as f:
                page = f.read()
        finally:
            if os.path.exists(out):
                os.remove(out)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn('"onerror="', page)
        self.assertIn("&lt;script&gt;", page)

    def test_settled_page_marks_every_outcome_and_totals_them(self):
        """The evening page is the morning page with results on it.

        The badge map is keyed on engine/grade.py's own lowercase constants. An uppercase
        key here matched nothing and rendered a fully settled day as all-pending — the
        page looked right and said the opposite of the truth, which is the worst kind of
        reporting bug.
        """
        for key in ("win", "loss", "push", "half"):
            self.assertIn(key, make_picks_page.RESULTS_TR,
                          f"grade.py emits {key!r} and the page cannot render it")
        self.assertEqual(
            sorted(make_picks_page.RESULTS_TR),
            sorted([grade.WIN, grade.LOSS, grade.PUSH, grade.HALF]))

        log = []
        for i, res in enumerate([grade.WIN] * 3 + [grade.LOSS, grade.PUSH, None], 1):
            log.append({
                "date": "2026-07-26", "id": i, "score": 90.0 - i, "band": "güçlü",
                "model_pct": 90.0 - i, "evidence_pct": 100.0, "model_survival": 0.9,
                "p1": f"Ev {i}", "p2": f"Dep {i}", "league": "Test Ligi", "sport_id": 1,
                "start": "2026-07-26T16:00:00+00:00", "odds": 1.5,
                "selection_tr": "Toplam gol 5.5 altı", "url": "https://x.test/1",
                "result": res, "final_score": [2, 1] if res else None,
            })
        report = tools_daily_results.as_report("2026-07-26", log)
        out = os.path.join(ROOT, "fixtures", "_tmp_results.html")
        try:
            make_picks_page.build(report, out)
            with open(out, encoding="utf-8") as f:
                page = f.read()
        finally:
            if os.path.exists(out):
                os.remove(out)

        # Count the BADGES, not the word: the footer explains what a pending selection
        # is not counted as, and that sentence names the outcomes too.
        badge = lambda css, txt: page.count(f'class="badge {css}">{txt}')
        self.assertEqual(badge("win", "KAZANDI"), 3)
        self.assertEqual(badge("loss", "KAYBETTİ"), 1)
        self.assertEqual(badge("push", "İADE"), 1)
        # The one with no result must be shown as pending, never as a silent blank.
        self.assertIn("BEKLİYOR", page)
        self.assertIn('data-result="pending"', page)
        # Hit rate counts decided legs only: 3 wins of 4 decided, the push set aside.
        s = report["summary"]
        self.assertEqual((s["win"], s["loss"], s["push"], s["graded"]), (3, 1, 1, 5))
        self.assertAlmostEqual(s["hit_rate"], 0.75)
        self.assertIn("%75.0", page)

    def test_a_model_is_admitted_only_by_held_out_calibration(self):
        """The gate that replaces judgement about whether a sport is "ready".

        Two bugs reached a live card before this existed: a basketball handicap with its
        sign flipped, claiming 90.4% where the truth was 74.9%, and a table tennis logistic
        extrapolated to 97% on a 3.30 shot. Neither looks wrong and both clear
        MIN_MODEL_SURVIVAL — the confidence floor CANNOT catch them, because the floor
        trusts the model. Only a comparison against unseen matches can.
        """
        for sid in sorted(results_store.summary()):
            model = model_generic.load(sid)
            if not model:
                continue
            ok, why = model_generic.usable(model)
            if not ok:
                continue
            ho = model.get("calibration_holdout") or {}
            self.assertTrue(ho.get("test"), f"sport {sid} was admitted with no holdout")
            self.assertGreaterEqual(
                ho["test"], 100,
                f"sport {sid} was admitted on {ho['test']} unseen matches")
            # The check must be capable of failing: an identical train and test set would
            # report a perfect 0.000 and mean nothing.
            self.assertGreater(ho["train"], ho["test"])
            for c in model["calibration"]:
                self.assertLess(abs(c["predicted"] - c["observed"]), 0.03,
                                f"sport {sid} admitted with +{c['line']} off by "
                                f"{c['predicted'] - c['observed']:+.3f}")

    def test_a_distribution_only_answers_questions_in_its_own_unit(self):
        """The store records table tennis in SETS, so it must refuse a POINTS market.

        This is not hypothetical. The generic model priced "Toplam sayı 76.5 altı" — total
        points under 76.5 — from a distribution whose totals are the number of sets played,
        every one of them between 3 and 5. "Under 76.5" came back at 100.00% on a 1.79
        shot, and it would have gone onto a live slip. A distribution answers questions
        asked in its own unit and no others.
        """
        sets = {"margin_pmf": {-3.0: 0.2, -1.0: 0.3, 1.0: 0.3, 3.0: 0.2},
                "total_pmf": {3.0: 0.4, 4.0: 0.35, 5.0: 0.25},
                "sample_n": 900, "unit": "sets", "_source": "generic"}
        # Group 17 counts POINTS in table tennis. Refused outright.
        self.assertIsNone(model_generic.rung_probs(
            {"market_key": ("k", "17|76.5"), "outcome_id": 10}, sets))
        # Group 2 is a POINT handicap in a set-scored sport. Also refused.
        self.assertIsNone(model_generic.rung_probs(
            {"market_key": ("k", "2|-4.5"), "outcome_id": 8}, sets))
        # The markets it DOES measure are priced: set handicap and total sets.
        self.assertIsNotNone(model_generic.rung_probs(
            {"market_key": ("k", "7099|-1.5"), "outcome_id": 5750}, sets))
        self.assertIsNotNone(model_generic.rung_probs(
            {"market_key": ("k", "2604|3.5"), "outcome_id": 9}, sets))
        # And a goals-scored sport is the mirror image.
        goals = dict(sets, unit="goals")
        self.assertIsNotNone(model_generic.rung_probs(
            {"market_key": ("k", "17|2.5"), "outcome_id": 9}, goals))
        self.assertIsNone(model_generic.rung_probs(
            {"market_key": ("k", "7099|-1.5"), "outcome_id": 5750}, goals))

    def test_a_counted_probability_is_never_certain(self):
        """"Never observed in 900 matches" is not "impossible".

        A 1.000 clears every gate in this product, so the counted probability is held
        inside what the sample can support. On a large band the correction is invisible;
        on a small one it is the entire point.
        """
        probs = {"margin_pmf": {1.0: 0.5, 3.0: 0.5},     # the home side never loses here
                 "total_pmf": {4.0: 1.0}, "sample_n": 30,
                 "unit": "goals", "_source": "generic"}
        win, _ = model_generic.rung_probs(
            {"market_key": ("k", "2|0.5"), "outcome_id": 7}, probs)
        self.assertLess(win, 1.0)
        self.assertGreater(win, 0.9)
        # And the mirror side keeps the pair summing to one: a cap applied to only one
        # end produces two numbers that are not a probability pair.
        loss, _ = model_generic.rung_probs(
            {"market_key": ("k", "2|0.5"), "outcome_id": 8}, probs)
        self.assertAlmostEqual(win + loss, 1.0, places=9)
        # A bigger sample earns a claim closer to certainty, but never reaches it.
        big = dict(probs, sample_n=100_000)
        wider, _ = model_generic.rung_probs(
            {"market_key": ("k", "2|0.5"), "outcome_id": 7}, big)
        self.assertGreater(wider, win)
        self.assertLess(wider, 1.0)

    def test_a_womens_or_youth_side_is_never_priced_from_the_senior_team(self):
        """A variant marker makes it a DIFFERENT team, not a fuzzier match.

        This guard exists in engine/model_elo.py and was dropped when the matcher was
        generalized. The cost showed up immediately: the generic football model priced
        "Corinthians Paulista (Women)" from the MEN'S Brazilian Serie A ratings and called
        a +6.5 handicap 99.78%, and did the same for Danish, Scottish and Brazilian U20
        fixtures. The book puts these on the same card as the senior games, so it is not a
        rare edge — it was four of the model's most confident selections of the day.
        """
        model = {"pools": {"": {"Corinthians": 1700.0, "Vitoria": 1400.0}},
                 "appearances": {"": {"Corinthians": 500, "Vitoria": 500}},
                 "aliases": {}, "line": {"slope": 0.01, "intercept": 0.0,
                                         "mean_abs_margin": 1.0},
                 "bands": {"": [{"lo": -9, "hi": 9, "n": 900, "margin": {"0": 1}}]},
                 "_margin": {"": [{0.0: 1.0}]}, "_total": {"": [{2.0: 1.0}]}}
        # The senior fixture prices.
        self.assertIsNotNone(model_generic.lookup(model, "Corinthians", "Vitoria")[0])
        # Every variant of it does not, in either position.
        for a, b in (("Corinthians (Women)", "Vitoria (Women)"),
                     ("Corinthians U20", "Vitoria U20"),
                     ("Corinthians", "Vitoria (Women)"),
                     ("Corinthians B", "Vitoria")):
            self.assertIsNone(model_generic.lookup(model, a, b)[0],
                              f"{a} v {b} was priced from the senior ratings")
        for name, want in (("Palmeiras", ""), ("Palmeiras U20", "u20"),
                           ("Nordsjaelland (Women)", "women"), ("Real Madrid", "")):
            self.assertEqual(model_generic.variant(name), want)

    def test_a_provisional_rating_never_prices_a_fixture(self):
        """A side seen twice still sits at the 1500 it started from, and 1500 means
        "we have not measured this", not "average". Pricing from it makes every mismatch
        look like a coin flip — which is exactly how tennis first failed its calibration
        by 7.4 points, the tour being full of qualifiers who appear once."""
        model = {"pools": {"": {"A": 1700.0, "B": 1300.0}},
                 "appearances": {"": {"A": 500, "B": 3}},
                 "aliases": {}, "line": {"slope": 0.01, "intercept": 0.0,
                                         "mean_abs_margin": 1.0},
                 "bands": {"": [{"lo": -9, "hi": 9, "n": 900, "margin": {"0": 1}}]},
                 "_margin": {"": [{0.0: 1.0}]}, "_total": {"": [{2.0: 1.0}]}}
        self.assertIsNone(model_generic.lookup(model, "A", "B")[0])
        model["appearances"][""]["B"] = model_generic.MIN_APPEARANCES
        self.assertIsNotNone(model_generic.lookup(model, "A", "B")[0])

    def test_ratings_are_taken_as_they_stood_before_the_match(self):
        """Hindsight ratings describe a match by how good the two sides turned out to be
        over the WHOLE history — including that match and everything after it.

        Fitting on them was the single largest error in this model. Football, basketball
        and tennis all systematically over-rated the underdog at the tightest line until
        the pre-match gap was separated out; football went from a 0.043 calibration gap to
        0.010 on the same data, with nothing else changed.
        """
        rows = [
            {"date": "2025-01-01", "home": "A", "away": "B", "home_score": 5, "away_score": 0},
            {"date": "2025-01-02", "home": "A", "away": "B", "home_score": 5, "away_score": 0},
            {"date": "2025-01-03", "home": "A", "away": "B", "home_score": 5, "away_score": 0},
        ]
        final, gaps = model_generic.fit_ratings(rows, record=True)
        self.assertEqual(len(gaps), len(rows))
        # The first meeting is priced from equal ratings plus the home term, and each
        # later one from a gap that has widened. A final-rating fit would have used the
        # widest gap for all three, including the one played before anyone knew it.
        self.assertAlmostEqual(gaps[0], model_generic.HOME_ELO)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])
        self.assertGreater(final[("", "A")], final[("", "B")])

    def test_a_sport_with_too_little_history_is_refused(self):
        """Refusing is a feature. A thin sample will happily report 100% cover rates."""
        thin = {"games": 40, "calibration": [{"line": 1.5, "predicted": 0.9,
                                              "observed": 0.9}]}
        ok, why = model_generic.usable(thin)
        self.assertFalse(ok)
        self.assertIn("40", why)
        ok, why = model_generic.usable({"games": 5000, "calibration": []})
        self.assertFalse(ok, "a model with no calibration table must never be admitted")
        skewed = {"games": 5000, "calibration": [{"line": 1.5, "predicted": 0.90,
                                                  "observed": 0.74}]}
        self.assertFalse(model_generic.usable(skewed)[0])

    def test_generic_handicap_probability_moves_the_right_way(self):
        """A bigger head start is safer, and the two sides of one line sum to 1.

        Counted rather than fitted, so there is no expression to get backwards — which is
        the structural reason the basketball sign error cannot recur here.
        """
        pmf = {-3.0: 0.1, -1.0: 0.2, 0.0: 0.2, 1.0: 0.2, 4.0: 0.2, 9.0: 0.1}
        probs = {"margin_pmf": pmf, "total_pmf": {5.0: 1.0}, "sample_n": 5000,
                 "unit": "goals", "_source": "generic"}
        last = 0.0
        for line in (0.5, 1.5, 2.5, 3.5, 5.5):
            row = {"market_key": ("k", f"2|{-line}"), "outcome_id": 8}   # away +line
            win, _push = model_generic.rung_probs(row, probs)
            self.assertGreaterEqual(win, last, f"+{line} came out no safer than below it")
            last = win
        home = model_generic.rung_probs(
            {"market_key": ("k", "2|-2.5"), "outcome_id": 7}, probs)[0]
        away = model_generic.rung_probs(
            {"market_key": ("k", "2|-2.5"), "outcome_id": 8}, probs)[0]
        self.assertAlmostEqual(home + away, 1.0, places=9)

    def test_ratings_never_cross_a_pool(self):
        """Football divisions do not play each other, so their ratings are not comparable.

        Pooling all 46 of them onto one scale was tried and football failed its own
        calibration by 4.8 points at +0.5 — a mid-table League Two side was being called
        the equal of a mid-table Premier League side. Generalizing a model is precisely
        when a sport's real structure gets dropped.
        """
        rows = [
            {"date": "2025-01-01", "home": "A", "away": "B", "home_score": 3,
             "away_score": 0, "pool": "top"},
            {"date": "2025-01-02", "home": "C", "away": "D", "home_score": 3,
             "away_score": 0, "pool": "bottom"},
        ]
        rating = model_generic.fit_ratings(rows)
        self.assertIn(("top", "A"), rating)
        self.assertIn(("bottom", "C"), rating)
        model = {"pools": {"top": {"A": 1600.0, "B": 1400.0},
                           "bottom": {"C": 1600.0, "D": 1400.0}},
                 # Both sides need enough matches behind them to be priced at all: a
                 # provisional rating sits at the 1500 it started from, and 1500 means
                 # "not measured", not "average".
                 "appearances": {"top": {"A": 99, "B": 99},
                                 "bottom": {"C": 99, "D": 99}},
                 "aliases": {}, "line": {"slope": 0.01, "intercept": 0.0,
                                         "mean_abs_margin": 1.0},
                 "bands": {"": [{"lo": -9, "hi": 9, "n": 500, "margin": {"0": 1}}]},
                 "_margin": {"": [{0.0: 1.0}]}, "_total": {"": [{2.0: 1.0}]}}
        # A and D never share a pool, so the fixture cannot be priced at all.
        self.assertIsNone(model_generic.lookup(model, "A", "D")[0])
        self.assertIsNotNone(model_generic.lookup(model, "A", "B")[0])

    def test_every_modelled_sport_has_a_live_signal(self):
        """A sport that produces selections must have something marked live behind it.

        The registry said table tennis had ZERO live signals for weeks after its model was
        fitted and wired, and nothing noticed until a generated page put the two side by
        side. A modelled sport with no live signal is either a stale registry or a model
        running on nothing, and both need to be seen.
        """
        for sid in pick.MODELLED_SPORTS:
            cov = signals.coverage(sid)[sid]
            self.assertGreater(
                cov["live"], 0,
                f"sport {sid} is modelled but engine/signals.py lists no live signal")

    def test_method_page_reports_coverage_without_flattering_it(self):
        """The generated method page must state the gap, not imply it away.

        1,261 researched mappings against 2 modelled sports is the honest headline, and a
        long table is very good at implying the opposite.
        """
        out = os.path.join(ROOT, "fixtures", "_tmp_method.html")
        try:
            groups, mappings = make_method_page.build(out)
            with open(out, encoding="utf-8") as f:
                page = f.read()
        finally:
            if os.path.exists(out):
                os.remove(out)

        self.assertGreater(groups, 10)
        self.assertGreater(mappings, 500)
        self.assertIn(str(len(pick.MODELLED_SPORTS)), page)
        for needle in ("Modelli", "Merdiven hazır, model yok", "Kapsam dışı",
                       "puan = 100", "MIN_ODDS"):
            self.assertIn(needle, page)
        # Self-contained, like every page this project attaches to a Telegram message.
        self.assertNotIn("<script src", page)
        self.assertNotIn("<link", page)

    def test_telegram_caption_never_splits_a_tag(self):
        """Telegram caps a caption at 1024 characters and rejects the whole upload if the
        cut lands inside an HTML tag. Clipping on a line boundary is what prevents a
        working report from failing to send over a formatting detail."""
        notice = "\n".join(f"<b>satır {i}</b> uzun bir açıklama metni" for i in range(60))
        clipped = telegram.chunks(notice, 1000)[0]
        self.assertLessEqual(len(clipped), 1000)
        self.assertEqual(clipped.count("<b>"), clipped.count("</b>"))

    def test_the_watcher_reads_the_format_instead_of_assuming_it(self):
        """The live watcher decides a match is over from the book's own format note.

        This matters most exactly where the collector is most useful. Table tennis runs
        best-of-five and best-of-seven on the SAME day — Setka Cup against Masters — so
        3-1 is a finished match on one circuit and a 3-1 lead on the other. Assuming
        either would write down a wrong result at the precise moment the watcher is
        earning its keep."""
        def game(note, sport=10):
            return {"MIS": [{"K": 1, "V": "Group A"}, {"K": 3, "V": note}]}

        self.assertEqual(collect_live.format_of(game("5 Games Match"), 10), ("target", 3))
        self.assertEqual(collect_live.format_of(game("7 Games Match"), 10), ("target", 4))
        # The explicit form wins over the headline count when the note carries both.
        self.assertEqual(
            collect_live.format_of(game("7 Frames Match (4 Frames up to win)", 30), 30),
            ("target", 4))
        self.assertEqual(collect_live.format_of(game("Best of 3 maps"), 40), ("target", 2))
        # Duration notation is a PERIOD count, not a race: 4x10 is four quarters.
        self.assertEqual(collect_live.format_of(game("4x10"), 3), ("periods", 4))
        self.assertEqual(collect_live.format_of(game("3x5"), 2), ("periods", 3))
        # No note: a sport with a single format may fall back to it, one with several
        # may NOT, and the ones with several are exactly tennis and table tennis.
        self.assertEqual(collect_live.format_of({}, 6), ("target", 3))
        self.assertEqual(collect_live.format_of({}, 1), ("periods", 2))
        self.assertEqual(collect_live.format_of({}, 10), ("target", None))
        self.assertEqual(collect_live.format_of({}, 4), ("target", None))

    def test_the_watcher_refuses_a_match_it_cannot_prove_is_over(self):
        """A watcher that guesses is worse than no watcher.

        Every result this collector writes down goes straight into a rating, and a match
        recorded at the score it held when the feed hiccuped is indistinguishable from a
        real one afterwards. So each branch that cannot answer refuses, and the cost of
        refusing is one result rather than a corrupted history."""
        def rec(**kw):
            base = {"sport": 10, "kind": "target", "n": 4, "s1": 4, "s2": 2, "period": 0}
            base.update(kw)
            return base

        self.assertTrue(collect_live.looks_finished(rec()))
        # A best-of-SEVEN at 3-1 is a lead, not a result.
        self.assertFalse(collect_live.looks_finished(rec(s1=3, s2=1)))
        # The same score on a best-of-five is the match.
        self.assertTrue(collect_live.looks_finished(rec(n=3, s1=3, s2=1)))
        # Unreadable format: refuse rather than fall back to something plausible.
        self.assertFalse(collect_live.looks_finished(rec(n=None)))
        # Both sides at the target means we are reading a running total, not a final one.
        self.assertFalse(collect_live.looks_finished(rec(s1=4, s2=4)))
        # A PERIOD sport is never settled by inference, however complete it looks. A
        # football match at 1-0 in the second half satisfies every structural check and
        # may still finish 3-1, so recording it invents a scoreline. Being in the last
        # period is not being finished, and nothing in the payload turns one into the
        # other — so these are recorded only when the feed itself says so.
        foot = {"sport": 1, "kind": "periods", "n": 2, "s1": 2, "s2": 1, "period": 2}
        self.assertFalse(collect_live.looks_finished(foot))
        self.assertFalse(collect_live.looks_finished({**foot, "period": 9}))
        self.assertFalse(collect_live.looks_finished(
            {"sport": 3, "kind": "periods", "n": 4, "s1": 91, "s2": 88, "period": 4}))
        # And the feed saying so needs no inference at all.
        self.assertTrue(collect_live.is_finished_now({"cps": "Match finished"}))
        self.assertFalse(collect_live.is_finished_now({"cps": "2nd half"}))
        # Once the feed HAS said so, a race's target is not guessed but read off the
        # result: a race ends when somebody reaches it, so the winner's tally is it. That
        # recovers the fixtures whose format note the book omits — a real 0-4 at the CTT
        # World Championship was thrown away for want of a "7 Games Match" line.
        got = collect_live.settle_target(
            {"sport": 10, "kind": "target", "n": None, "s1": 0, "s2": 4})
        self.assertEqual(got["n"], 4)
        self.assertTrue(collect_live.placeable(got))
        self.assertEqual(collect_live.to_result({**got, "p1": "A", "p2": "B",
                                                 "start": 1_753_500_000}, 0)["pool"], "bo7")
        # A stated format is never overwritten by the score.
        self.assertEqual(collect_live.settle_target(
            {"sport": 10, "kind": "target", "n": 3, "s1": 3, "s2": 1})["n"], 3)
        # And a period sport has no target to settle.
        self.assertIsNone(collect_live.settle_target(
            {"sport": 1, "kind": "periods", "n": None, "s1": 2, "s2": 1}).get("n"))

    def test_a_watched_result_carries_identity_and_its_own_rating_scale(self):
        """What the watcher stores has to be usable by the generic model unchanged.

        Two details do the work. The book's participant ids survive a rename and a
        transliteration where a name does not, and a race to four sets is a different bet
        from a race to three — pooling them would rate a Masters player on a Setka Cup
        scale and price a best-of-seven handicap off best-of-five history."""
        row = collect_live.to_result(
            {"sport": 10, "league": "Masters. Russia", "p1": "A", "p2": "B",
             "id1": "2778933", "id2": "4097977", "s1": 4, "s2": 2, "start": 1_753_500_000,
             "kind": "target", "n": 4}, 1_753_500_000)
        self.assertEqual(row["home_id"], "2778933")
        self.assertEqual(row["pool"], "bo7")
        self.assertEqual(row["unit"], "sets")
        self.assertEqual(row["source"], "betwinner-live")
        # And the store accepts it as it stands — no adapter-side repair on the way in.
        self.assertIsNotNone(results_store.clean(row))
        five = collect_live.to_result(
            {"sport": 10, "p1": "A", "p2": "B", "s1": 3, "s2": 1, "start": 1_753_500_000,
             "kind": "target", "n": 3, "league": "Setka Cup"}, 1_753_500_000)
        self.assertEqual(five["pool"], "bo5")
        # A period sport has no such split, so it stays on one scale.
        self.assertNotIn("pool", collect_live.to_result(
            {"sport": 1, "p1": "A", "p2": "B", "s1": 1, "s2": 0, "start": 1_753_500_000,
             "kind": "periods", "n": 2, "league": "E0"}, 1_753_500_000))
        # Except where the FORMAT is the scale. A Test innings runs to three hundred and a
        # T20 innings to a hundred and eighty; pooled, the model would price a T20 run
        # handicap off scores no T20 can reach. So cricket is placed by its format note,
        # and a fixture without one is refused rather than dropped into the wrong pool.
        crick = {"sport": 66, "p1": "A", "p2": "B", "s1": 180, "s2": 175,
                 "start": 1_753_500_000, "kind": "periods", "n": 2, "note": "T20"}
        self.assertEqual(collect_live.to_result(crick, 0)["pool"], "T20")
        self.assertEqual(
            collect_live.to_result({**crick, "note": "Test Match"}, 0)["pool"], "Test Match")
        self.assertTrue(collect_live.placeable(crick))
        self.assertFalse(collect_live.placeable({**crick, "note": ""}))

    def test_a_second_model_may_fill_a_gap_but_never_overrule_a_refusal(self):
        """A fallback model answers where the first CANNOT reach, never where it declined.

        Table tennis runs two models: Setka's rating index reaches four times as many
        fixtures on a real card (70 of 350 against 18), and the generic one now holds Pro
        League, Masters and TT-Cup players from the live watcher that Setka's index does
        not carry at all — 3 fixtures on the measured card. Running them in sequence adds
        that reach.

        What it must NOT do is ask the second model when the first said no. The confidence
        floor exists to throw away what a model is not sure of; consulting another model
        until one clears the floor would select for whichever happens to be overconfident,
        and would do it invisibly. So the fallback is at the RESOLVE step — can this model
        price this fixture at all — and never at the pick step."""
        called = []

        def tt_lookup(_m, _i, home, _away):
            called.append(("setka", home))
            # Setka knows this player and has an opinion.
            return ({"_source": "setka"}, 1.0) if home == "known" else (None, 0.0)

        def generic_lookup(_m, home, _away, home_id=None, away_id=None):
            called.append(("generic", home))
            return {"_source": "generic"}, 1.0

        # resolve() imports these inside the function, so patch the modules themselves.
        from engine import model_tt
        with mock.patch.object(model_tt, "lookup", tt_lookup), \
             mock.patch.object(model_generic, "lookup", generic_lookup):
            # Setka can price it: the generic model is never consulted, whatever the
            # ladder later decides about the rungs.
            probs, _score, source = pick.resolve(
                {"p1": "known", "p2": "x", "sport_id": 10},
                tt=("model", "index"), generic={10: "gen"})
            self.assertEqual(source, "setka")
            self.assertNotIn("generic", [c[0] for c in called])

            called.clear()
            # Setka cannot reach this player at all — that is a gap, not a refusal.
            probs, _score, source = pick.resolve(
                {"p1": "unknown", "p2": "x", "sport_id": 10},
                tt=("model", "index"), generic={10: "gen"})
            self.assertEqual(source, "generic")
            self.assertEqual([c[0] for c in called], ["setka", "generic"])

    def test_a_generated_competition_is_caught_without_touching_setka_cup(self):
        """A league is called generated on PHYSICAL IMPOSSIBILITY, nothing weaker.

        Two weaker signals were tried first and both flagged real competitions. Identical
        prices: six RHL fixtures were byte-identical across 35 markets, but so were four
        Setka Cup fixtures across 33 — the book templates prices for any thin market.
        A completed micro round-robin: RHL and UPVL both showed one, and so does Setka
        Cup, because that is genuinely how the circuit runs. Either rule would have
        deleted the sport behind 25,738 stored results and a 0.011 calibration.

        What separates them is whether a body could keep the schedule. Berkut Volgograd
        starts at 02:50 and again at 04:20; an ice hockey game is not over in ninety
        minutes. A Setka Cup player's matches sit thirty minutes apart and a best-of-five
        is done in eighteen."""
        hour = 3600

        def fx(pairs, sport):
            return [(a, b, t) for a, b, t in pairs], sport

        # RHL: a three-team cycle inside ninety minutes, in ice hockey.
        rhl, sport = fx([("berkut", "phoenix", 0),
                         ("phoenix", "elektronik", 40 * 60),
                         ("elektronik", "berkut", 90 * 60)], 2)
        bad, why = simulated.impossible_schedule(rhl, sport)
        self.assertTrue(bad)
        self.assertIn("üretilmiş", why)

        # The SAME schedule in table tennis is ordinary — the sport is the whole point.
        self.assertFalse(simulated.impossible_schedule(rhl, 10)[0])

        # Setka Cup's real shape: four players, a full round-robin, half-hour spacing.
        setka_like = [("a", "b", 0), ("c", "d", 30 * 60), ("a", "c", 60 * 60),
                      ("b", "d", 90 * 60), ("a", "d", 120 * 60), ("b", "c", 150 * 60)]
        self.assertFalse(simulated.impossible_schedule(setka_like, 10)[0])

        # A real group stage in a slow sport, spread over days, is fine too.
        spread = [("x", "y", 0), ("y", "z", 26 * hour), ("z", "x", 50 * hour)]
        self.assertFalse(simulated.impossible_schedule(spread, 2)[0])

        # One double-booked participant is a mislabelled fixture, not a fake league.
        single = [("p", "q", 0), ("p", "r", 30 * 60), ("s", "t", 5 * hour)]
        self.assertFalse(simulated.impossible_schedule(single, 2)[0])

        # And the flagged set survives a round trip to disk, which is how the live
        # watcher learns about it — it never sees a whole card itself.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sim.json")
            simulated.save({(2, "RHL"): "why"}, path)
            self.assertEqual(simulated.load(path), {(2, "RHL"): "why"})
        self.assertEqual(simulated.load("/nonexistent/sim.json"), {})

    def test_the_wait_for_a_sport_is_measured_not_asserted(self):
        """"When do the other sports show up" is answered from the collection ledger.

        It cannot be answered from the results store, and the first version tried: the
        store keeps each fixture's own DATE, not the moment we learned of it, so a watcher
        that had run for three hours looked exactly like one that had run for a day. It
        told the operator volleyball was 28 days away when the measured rate put it at
        four. The ledger records what was collected and when, so the rate is per hour of
        actual watching."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watch_log.jsonl")
            with open(path, "w") as f:
                for at, n in (("2026-07-26T22:35:00Z", 7), ("2026-07-26T23:57:00Z", 3)):
                    f.write(json.dumps({"at": at, "sport": 6, "added": n}) + "\n")
            ledger = [daily_report._read_ledger(path)]
            got = daily_report._eta(6, 14, _ledger=ledger)
        # 10 results over two runs 82 minutes apart. Two entries are two runs but only ONE
        # gap between them, so the watching time is the span scaled by n/(n-1) — crediting
        # both runs to one run's worth of hours would overstate the rate by half.
        self.assertIn("günde ~", got)
        self.assertIn("gün", got)
        rate = int(re.search(r"günde ~(\d+)", got).group(1))
        self.assertTrue(80 <= rate <= 95, got)

        # Too little to say anything with: say nothing rather than extrapolate from one.
        self.assertNotIn("günde ~", daily_report._eta(6, 14, _ledger=[[
            {"at": "2026-07-26T22:35:00Z", "sport": 6, "added": 7}]]))
        # A ledger that is not there at all is not an error.
        self.assertEqual(daily_report._read_ledger("/nonexistent/watch_log.jsonl"), [])

    def test_a_hit_rate_on_a_handful_of_legs_says_so(self):
        """A percentage over three legs looks exactly like one over three hundred.

        This project has twice been steered by a number that meant nothing: 87.1%
        computed from matches that had not kicked off, and 100% computed from a single
        leg. Both were arithmetically correct and both were printed in bold. The fix for
        the first two was to stop producing them; the fix for the general case is to say
        how much they rest on, on the PAGE and not only in the Telegram caption, because
        the page is where the number is actually read."""
        base = {"id": 1, "score": 90.0, "band": "güçlü", "p1": "A", "p2": "B",
                "sport_id": 1, "start": "2026-07-26T12:00:00+00:00", "odds": 1.5,
                "selection_tr": "x", "market_line": "17|2.5", "outcome_id": 10,
                "model_survival": 0.9, "league": "L", "window": 24}
        def page(picks, summary):
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "results.html")
                make_picks_page.build({"day": "2026-07-26", "picks": picks,
                                       "summary": summary}, out)
                with open(out) as f:
                    return f.read()

        thin = page([dict(base, result="win"), dict(base, id=2, result="loss")],
                    {"win": 1, "half": 0, "push": 0, "loss": 1, "hit_rate": 0.5,
                     "staked": 2, "returned": 1.5})
        self.assertIn("sonuçlanan seçime dayanıyor", thin)
        self.assertIn(str(make_picks_page.MIN_MEANINGFUL), thin)

        # Once there is enough behind it, the caveat goes away rather than nagging.
        many = page([dict(base, id=i, result="win") for i in range(40)],
                    {"win": 40, "half": 0, "push": 0, "loss": 0, "hit_rate": 1.0,
                     "staked": 40, "returned": 60.0})
        self.assertNotIn("sonuçlanan seçime dayanıyor", many)

    def test_a_result_recorded_the_other_way_round_is_swapped_not_dropped(self):
        """Which participant is "home" belongs to the SOURCE, not to the match.

        In table tennis and tennis there is no home side at all, so the book's O1/O2 and
        Setka's p1/p2 are ordered independently. Keying results one way silently lost
        matches that were sitting in the store — on the first real card, a Setka row read
        "Lukas Rulc 3-1 Ondrej Mezera" while the prediction was on Mezera.

        Losing them is the safe failure. Forgetting to swap the scores is the unsafe one:
        it settles the bet against the wrong player and reports it as a graded result."""
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "results")
            os.makedirs(store)
            with open(os.path.join(store, "10.jsonl"), "w") as f:
                f.write(json.dumps({"date": "2026-07-26", "home": "Lukas Rulc",
                                    "away": "Ondrej Mezera", "home_score": 3,
                                    "away_score": 1, "source": "setka"}) + "\n")
            with mock.patch.object(results_store, "STORE", store):
                _by_id, by_name = grade_predictions.store_results(10)

        start = "2026-07-26T14:15:00+00:00"
        # Asked in the store's own order: the scores come back as stored.
        self.assertEqual(
            grade_predictions.lookup_result(by_name, "Lukas Rulc", "Ondrej Mezera",
                                            start, elapsed_hours=10), (3, 1))
        # Asked the other way round: found, and SWAPPED.
        self.assertEqual(
            grade_predictions.lookup_result(by_name, "Ondrej Mezera", "Lukas Rulc",
                                            start, elapsed_hours=10), (1, 3))
        # Which is what makes the settlement right: Mezera lost by two sets, so +2.5
        # covers it and +1.5 does not.
        got = grade_predictions.lookup_result(by_name, "Ondrej Mezera", "Lukas Rulc",
                                              start, elapsed_hours=10)
        self.assertEqual(
            grade.settle({"market_key": (0, "7099|2.5"), "outcome_id": 5749}, *got),
            grade.WIN)
        self.assertEqual(
            grade.settle({"market_key": (0, "7099|1.5"), "outcome_id": 5749}, *got),
            grade.LOSS)

    def test_a_running_match_is_never_graded(self):
        """The grader must not be able to settle a fixture that is still being played.

        This is the second time this project produced a hit rate out of previous meetings.
        The first was 87.1% from 31 predictions that had not kicked off. The second was
        found within minutes of routing grading through the results store: "San Francisco
        Giants +2.5" settled as a WIN at 9-2, seventy-five minutes after first pitch,
        because the same two teams had met the day before and the date match allowed one
        day of slack. One prediction, 100% hit rate, and the number every later change is
        supposed to be steered by."""
        start = "2026-07-26T20:05:00+00:00"
        self.assertFalse(grade_predictions.finished_enough(
            5, start, "2026-07-26T21:20:00+00:00"))
        self.assertTrue(grade_predictions.finished_enough(
            5, start, "2026-07-26T23:30:00+00:00"))
        # A table tennis match is over in half an hour and must not wait on a football
        # clock, or a whole sport grades a day late.
        self.assertTrue(grade_predictions.finished_enough(
            10, start, "2026-07-26T20:45:00+00:00"))
        # Unreadable timestamps refuse rather than default to "probably finished".
        self.assertFalse(grade_predictions.finished_enough(1, None, "2026-07-26T23:00:00"))

        # Same date wins even when an adjacent one appears first in the list.
        entries = [("2026-07-25", 9, 2), ("2026-07-26", 1, 4)]
        self.assertEqual(
            grade_predictions._nearest(entries, start, 1, elapsed_hours=20.0), (1, 4))
        # And an adjacent date alone cannot answer until today's result has had time to
        # appear and has not — otherwise yesterday's meeting settles tonight's bet.
        yesterday = [("2026-07-25", 9, 2)]
        self.assertIsNone(
            grade_predictions._nearest(yesterday, start, 1, elapsed_hours=1.2))
        self.assertEqual(
            grade_predictions._nearest(yesterday, start, 1, elapsed_hours=20.0), (9, 2))

    def test_the_books_own_id_beats_a_name_match(self):
        """Where the card and the store share the book's participant id, use it.

        Name matching is the weakest link in this pipeline. It needs a fuzzy threshold, it
        needs a guard against "(Women)" and "U20" resolving to the senior side — a guard
        that was once dropped and immediately priced a women's fixture at 99.78% off the
        men's ratings — and it still fails on a transliteration or a sponsor rename. An id
        has none of those failure modes, and the live watcher takes it off the same feed
        the card is built from, so for anything it collected the two sides share a key
        that no spelling can break."""
        model = {
            "sport_id": 99,
            "pools": {"": {"Alpha FC": 1600.0, "Beta United": 1500.0}},
            "appearances": {"": {"Alpha FC": 50, "Beta United": 50}},
            "book_ids": {"": {"111": "Alpha FC", "222": "Beta United"}},
            "bands": {"": [{"lo": -9, "hi": 9, "n": 900,
                            "margin": {0: 300, 1: 300, -1: 300},
                            "total": {2.0: 900}}]},
            "line": {"slope": 0.004, "intercept": 0.0, "mean_abs_margin": 1.0},
            "unit": "goals",
        }
        model["_margin"] = {k: [model_generic._pmf(b["margin"]) for b in v]
                            for k, v in model["bands"].items()}
        model["_total"] = {k: [model_generic._pmf(b["total"]) for b in v]
                           for k, v in model["bands"].items()}
        # Names the matcher could never resolve — a rename and a transliteration.
        probs, score = model_generic.lookup(
            model, "Alpha Sportclub 1902", "Бета Юнайтед", home_id=111, away_id=222)
        self.assertIsNotNone(probs)
        self.assertEqual(probs["_teams"], ("Alpha FC", "Beta United"))
        self.assertEqual(score, 1.0)
        # Without the ids, the same fixture is refused rather than guessed at.
        self.assertIsNone(
            model_generic.lookup(model, "Alpha Sportclub 1902", "Бета Юнайтед")[0])
        # An id the store has never seen falls back to the name, not to a wrong team.
        self.assertIsNone(
            model_generic.lookup(model, "Nothing Like It", "Beta United",
                                 home_id=999, away_id=222)[0])
        # And the normalized card carries the ids in the first place, or none of the
        # above ever fires on a real fixture.
        rows = bwfeed.normalize(_sample())
        self.assertTrue(any(r.get("p1_id") and r.get("p2_id") for r in rows))

    def test_a_sport_skipped_before_fetching_is_still_reported(self):
        """Cutting the fetch must not cut the coverage report.

        The fetcher now drops excluded sports and non-head-to-head entries while reading
        the fixture list, instead of after pulling a thousand markets for each of them —
        on a live card that was 750 lottery draws and 311 races and outrights. But those
        sports then never reach the normalized rows, and the coverage report is built from
        those rows, so they would silently vanish from the one place that says what is on
        the card and why it was left out. "Only football and table tennis" was true for
        weeks precisely because nothing said so where it would be read."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            card = os.path.join(tmp, "card.json.gz")
            # Through the fetcher's own helper, so writer and reader cannot drift into
            # two filenames and quietly report a trimmed card as a complete one.
            with open(fetch_window.skipped_path(card), "w") as f:
                json.dump({"excluded_sport": {"82": 731, "314": 14},
                           "not_head_to_head": {"44": 151}}, f)
            got = daily_report.skipped_at_fetch(card)
            self.assertEqual(got[82]["matches"], 731)
            self.assertEqual(got[44]["reason"], "not_head_to_head")

            rows = [{"sport_id": 1, "fixture_id": 7, "match_id": 7}]
            results = [{"hours": 48, "picks": [], "matches": 1}]
            cov = daily_report.coverage(rows, results, {}, card_path=card)
            by_sport = {c["sport_id"]: c for c in cov}
            self.assertIn(82, by_sport)
            self.assertEqual(by_sport[82]["matches"], 731)
            self.assertEqual(by_sport[82]["state"], "excluded")
            self.assertIn(44, by_sport)
            self.assertEqual(by_sport[44]["state"], "excluded")
            # Biggest first, so the report opens on what actually fills the card.
            self.assertEqual([c["matches"] for c in cov],
                             sorted((c["matches"] for c in cov), reverse=True))
        # A missing sidecar is not an error: an older card simply reports what it has.
        self.assertEqual(daily_report.skipped_at_fetch("/nonexistent/card.json.gz"), {})

    def test_the_watch_list_is_a_list_of_finish_conditions(self):
        """A sport is watched only when we can say what finishing it looks like.

        The temptation is to sweep everything the book runs and sort it out later. But
        `data/results/` feeds ratings directly, and there is no honest finish rule for a
        marble race, a card game or a simulated FIFA ladder — nor is there anything worth
        modelling in one. The watch list IS the statement of what we can settle."""
        for sport, (unit, kind, n) in collect_live.SPORTS.items():
            self.assertIn(kind, ("target", "periods"), sport)
            self.assertIn(unit, ("goals", "points", "runs", "sets", "frames", "maps"),
                          sport)
            self.assertTrue(n is None or n >= 1, sport)
            # A unit the model cannot price would store history nothing reads.
            self.assertTrue(
                unit in model_generic.HANDICAP_GROUPS
                or unit in model_generic.TOTAL_GROUPS, f"sport {sport} unit {unit}")
        for excluded in config.EXCLUDED_SPORTS:
            self.assertNotIn(excluded, collect_live.SPORTS)


if __name__ == "__main__":
    if "--update" in sys.argv:
        rows = build_report()
        with open(SNAPSHOT, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"Wrote {len(rows)} rows to {SNAPSHOT}")
    else:
        unittest.main()
