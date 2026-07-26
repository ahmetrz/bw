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
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from engine import bwfeed, grade, ladder, pick, score, settlement, telegram  # noqa: E402

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
        ]
        for label, r, hg, ag, expected in cases:
            self.assertEqual(grade.settle(r, hg, ag), expected, label)

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

    def test_book_is_betwinner(self):
        """A direct pull is Betwinner by construction, so the mismatch banner must
        stay silent on this fixture."""
        with open(SAMPLE) as f:
            data = json.load(f)
        self.assertTrue(bwfeed.is_bwfeed(data))
        self.assertIn(config.BOOK, bwfeed.books_in(data))


if __name__ == "__main__":
    if "--update" in sys.argv:
        rows = build_report()
        with open(SNAPSHOT, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"Wrote {len(rows)} rows to {SNAPSHOT}")
    else:
        unittest.main()
