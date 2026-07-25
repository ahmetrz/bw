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
from engine import bwfeed, score  # noqa: E402

SAMPLE = os.path.join(ROOT, "fixtures", "sample.json")
SNAPSHOT = os.path.join(ROOT, "fixtures", "expected_report.json")

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
        cap = getattr(config, "MAX_PER_FIXTURE", 0)
        if cap:
            worst = fixtures.most_common(1)[0]
            self.assertLessEqual(worst[1], cap, f"fixture {worst[0]} exceeded the cap")

    def test_ranked_descending(self):
        s = [r["total_score"] for r in self.actual]
        self.assertEqual(s, sorted(s, reverse=True))

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
