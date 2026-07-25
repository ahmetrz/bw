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
from engine import bwfeed, ladder, score, settlement  # noqa: E402

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
