"""Regression + integration tests for the football+tennis combine platform's shared
engine — the pipeline layer beneath tests/test_combine_platform.py's own suite.

Standard library only — the project takes no pip dependencies for the core pipeline.

    python -m unittest discover -s tests -v
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
from engine import (bwfeed, coupon, grade, ladder, mirror, model_generic,  # noqa: E402
                    parlay, pick, rating, results_store, settlement, signals,
                    simulated, telegram)
from tools import collect_live, grade_predictions, heartbeat, refresh_combine  # noqa: E402

SAMPLE = os.path.join(ROOT, "fixtures", "sample.json")


def _sample():
    with open(SAMPLE) as f:
        return json.load(f)


class TestRegression(unittest.TestCase):
    def test_settlement_is_stated_for_football(self):
        """A prediction app must say what a bet means. Football settlement is confirmed
        (90 minutes), so every football row must carry a settlement scope of 'regulation'
        and must NOT be flagged as needing confirmation."""
        rows = bwfeed.normalize(_sample())
        settlement.annotate(rows)
        football = [r for r in rows if r.get("sport_id") == 1]
        self.assertTrue(football, "sample should contain football rows")
        for r in football:
            s = r["settlement"]
            self.assertEqual(s["scope"], "regulation")
            self.assertFalse(s["needs_confirmation"], "football settlement is confirmed")

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

    def test_outrights_are_suppressed(self):
        """An entry with no second participant is not a head-to-head, and must not parse.

        The feed uses an empty O2 for tournament winners, election questions, novelty
        bundles that appear even inside football, and multi-runner races. All of them
        break the machinery downstream: the one-selection-per-match rule has nothing to
        bind on, and the safety ladder has no two-outcome market to walk down.

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
        # "betwinner" is not a config knob — engine/bwfeed.py's own normalize() defaults
        # to it, and this whole repo exists for one book.
        self.assertIn("betwinner", bwfeed.books_in(data))

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
            # report a perfect 0.000 and mean nothing. The direct fact that guarantees
            # that cannot happen is TRAIN ending before TEST begins (no chronological
            # overlap) — checked directly here rather than via train-row-count >
            # test-row-count, which was only ever a proxy for it and stopped holding once
            # tools/build_generic_model.py switched to a date-proportional split
            # (pmc-2026-08-06-tennis-split): a sport whose recent collection is far
            # denser than its archive (table tennis, via the live watcher) can have MORE
            # rows in a 20%-of-TIME test window than in the 80%-of-time train one, while
            # remaining a perfectly genuine, non-overlapping holdout.
            self.assertTrue(ho.get("train_to") and ho.get("from"),
                            f"sport {sid} calibration_holdout is missing date range fields")
            self.assertLessEqual(ho["train_to"], ho["from"],
                                 f"sport {sid} train data ({ho['train_to']}) overlaps "
                                 f"test data ({ho['from']}) — not a real holdout")
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
        """Every sport actually in the product's scope must have something marked live
        behind it.

        The registry said table tennis had ZERO live signals for weeks after its model was
        fitted and wired, and nothing noticed until a generated page put the two side by
        side. A sport with no live signal is either a stale registry or a model running on
        nothing, and both need to be seen. Checked over config.COMBINE_SPORTS rather than
        pick.MODELLED_SPORTS: the latter is the (now empty) list of HAND-WRITTEN models —
        see engine/pick.py — and both football and tennis run on the generic model, not on
        one of those.
        """
        for sid in config.COMBINE_SPORTS:
            cov = signals.coverage(sid)[sid]
            self.assertGreater(
                cov["live"], 0,
                f"sport {sid} is in scope but engine/signals.py lists no live signal")

    def test_the_watcher_reads_the_format_instead_of_assuming_it(self):
        """The live watcher decides a match is over from the book's own format note.

        Tennis is the sport this matters most for: it runs best-of-three and best-of-five
        on the SAME tour, on the SAME day, with no format note published at all, so 2-0 is
        a finished match in one and a lead in the other. Assuming either would write down a
        wrong result at the precise moment the watcher is earning its keep — see
        test_tennis_is_collectable_even_though_it_states_no_format for that path in full;
        this test is the underlying note parser."""
        def game(note, sport=4):
            return {"MIS": [{"K": 1, "V": "Group A"}, {"K": 3, "V": note}]}

        # Football genuinely publishes short-sided period notation on the card ("Short
        # Football 3x3" at 2x5, "Subsoccer" at 2x5, "MLS+" at 2x10) — real notes, not
        # invented ones.
        self.assertEqual(collect_live.format_of(game("4x10", 1), 1), ("periods", 4))
        self.assertEqual(collect_live.format_of(game("3x5", 1), 1), ("periods", 3))
        # Tennis never actually publishes these forms today (it declares nothing at all —
        # see below), but the parser itself is sport-agnostic string matching and has to
        # be right regardless of which "target"-kind sport eventually sends it one.
        self.assertEqual(collect_live.format_of(game("5 Games Match"), 4), ("target", 3))
        self.assertEqual(collect_live.format_of(game("7 Games Match"), 4), ("target", 4))
        # The explicit form wins over the headline count when the note carries both.
        self.assertEqual(
            collect_live.format_of(game("7 Sets Match (4 Sets up to win)"), 4),
            ("target", 4))
        self.assertEqual(collect_live.format_of(game("Best of 3 maps"), 4), ("target", 2))
        # No note: a sport with a single format falls back to it (football always has
        # one), one that runs several may NOT (tennis, Bo3 and Bo5 on the same card).
        self.assertEqual(collect_live.format_of({}, 1), ("periods", 2))
        self.assertEqual(collect_live.format_of({}, 4), ("target", None))

    def test_the_watcher_refuses_a_match_it_cannot_prove_is_over(self):
        """A watcher that guesses is worse than no watcher.

        Every result this collector writes down goes straight into a rating, and a match
        recorded at the score it held when the feed hiccuped is indistinguishable from a
        real one afterwards. So each branch that cannot answer refuses, and the cost of
        refusing is one result rather than a corrupted history."""
        def rec(**kw):
            base = {"sport": 4, "kind": "target", "n": 4, "s1": 4, "s2": 2, "period": 0}
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
        # A PERIOD sport is never settled by the SCORE, however complete it looks. A
        # football match at 1-0 in the second half satisfies every structural check and
        # may still finish 3-1, so recording it invents a scoreline. Being in the last
        # period is not being finished, and no reading of the score turns one into the
        # other — what says so is a different field entirely, the clock.
        foot = {"sport": 1, "kind": "periods", "n": 2, "s1": 2, "s2": 1, "period": 2,
                "cps": "2nd half", "ts": 3000, "sls": "50 minutes"}
        self.assertFalse(collect_live.looks_finished(foot))
        self.assertFalse(collect_live.looks_finished({**foot, "period": 9}))
        # A period sport with no CLOCK_FINISH entry (nobody has watched its clock to the
        # end — see collect_live.CLOCK_FINISH) stays refused however complete it looks.
        self.assertFalse(collect_live.looks_finished(
            {"sport": 3, "kind": "periods", "n": 4, "s1": 91, "s2": 88, "period": 4}))
        # And the feed saying so needs no inference at all.
        self.assertTrue(collect_live.is_finished_now({"cps": "Match finished"}))
        self.assertFalse(collect_live.is_finished_now({"cps": "2nd half"}))
        # Once the feed HAS said so, a race's target is not guessed but read off the
        # result: a race ends when somebody reaches it, so the winner's tally is it. That
        # recovers the fixtures whose format note the book omits — tennis declares one on
        # only a small minority of live fixtures.
        got = collect_live.settle_target(
            {"sport": 4, "kind": "target", "n": None, "s1": 0, "s2": 4})
        self.assertEqual(got["n"], 4)
        self.assertTrue(collect_live.placeable(got))
        self.assertEqual(collect_live.to_result({**got, "p1": "A", "p2": "B",
                                                 "start": 1_753_500_000}, 0)["pool"], "bo7")
        # A stated format is never overwritten by the score.
        self.assertEqual(collect_live.settle_target(
            {"sport": 4, "kind": "target", "n": 3, "s1": 3, "s2": 1})["n"], 3)
        # And a period sport has no target to settle.
        self.assertIsNone(collect_live.settle_target(
            {"sport": 1, "kind": "periods", "n": None, "s1": 2, "s2": 1}).get("n"))

    def test_the_clock_is_what_says_a_period_sport_is_over(self):
        """The score cannot end a football match; the clock can.

        Watched to the end on real fixtures: `TS` counts up to 5400 and stops, and `SLS`
        — the minute in words, "84 minutes" — goes EMPTY at the same moment. Three matches
        ended that way and only ONE of them ever displayed "Match finished", so two thirds
        of finished football was being dropped by a collector that could see it was over.

        Everything else about this rule is a fence around that one reading."""
        def foot(**kw):
            base = {"sport": 1, "kind": "periods", "n": 2, "s1": 2, "s2": 1, "period": 2,
                    "cps": "2nd half", "ts": 5400, "sls": "", "note": ""}
            base.update(kw)
            return base

        self.assertTrue(collect_live.looks_finished(foot()))
        # 0-0 is a result, and the one this used to lose: `FS` omits a zero, so a goalless
        # match looked like one that had not kicked off.
        self.assertTrue(collect_live.looks_finished(foot(s1=0, s2=0)))
        # A reported minute IS a running clock. This is the guard doing the real work.
        self.assertFalse(collect_live.looks_finished(foot(sls="90 minutes")))
        self.assertFalse(collect_live.looks_finished(foot(ts=5034, sls="84 minutes")))
        # Regulation not reached, whatever the status says.
        self.assertFalse(collect_live.looks_finished(foot(ts=2700)))
        self.assertFalse(collect_live.looks_finished(foot(ts=0)))
        # Extra time is still being played, and its goals are not the ones the markets we
        # price settle on. Refused twice over: by the period, and by the status wording.
        self.assertFalse(collect_live.looks_finished(foot(period=3)))
        self.assertFalse(collect_live.looks_finished(foot(cps="Extra time 1st half")))
        self.assertFalse(collect_live.looks_finished(foot(cps="Penalty shoot-out")))
        # A DECLARED shorter game has a shorter regulation, and it is read, not assumed:
        # an eighty-minute match is over at 4800 and is not still running at 5399.
        self.assertTrue(collect_live.looks_finished(foot(ts=4800, note="2x40")))
        self.assertFalse(collect_live.looks_finished(foot(ts=4700, note="2x40")))
        # Both note spellings, taken off a live card. The Australian FFSA match ended at
        # TS=5400/SLS='' with no note; a Student League match ended at TS=1800 on "2
        # Halves of 15 minutes"; an Indian FAO fixture declaring "2 halves of 40 minutes"
        # vanished at TS=4796 with SLS='79 minutes' and must be REFUSED — that is a
        # mid-match feed drop four seconds short of its own regulation.
        self.assertEqual(collect_live.regulation_seconds(
            {"sport": 1, "note": "2 Halves of 15 minutes"}), 1800)
        self.assertEqual(collect_live.regulation_seconds(
            {"sport": 1, "note": "2 halves of 40 minutes"}), 4800)
        self.assertEqual(collect_live.regulation_seconds({"sport": 1, "note": ""}), 5400)
        india = foot(ts=4796, sls="79 minutes", note="2 halves of 40 minutes", s1=1, s2=7)
        self.assertFalse(collect_live.looks_finished(india))
        # A countdown is still a clock. The book writes both "9 minutes" and
        # "10 min remaining"; neither is an empty SLS and neither may settle anything.
        self.assertFalse(collect_live.looks_finished(foot(sls="10 min remaining")))
        # And a sport whose clock nobody has watched to the end stays refused. Basketball
        # has a clock too; whether it counts up, down or resets each quarter is unknown
        # here, and a rule that assumed would settle games at half time.
        self.assertNotIn(3, collect_live.CLOCK_FINISH)
        self.assertFalse(collect_live.looks_finished(
            {"sport": 3, "kind": "periods", "n": 4, "s1": 91, "s2": 88, "period": 4,
             "cps": "4th quarter", "ts": 2400, "sls": ""}))
        # The vanish path also has to be able to PLACE the row, which for football means
        # refusing the five-minute-half games filed under the same sport id. That used to
        # be implied — every fixture this accepted was a race with a readable target — and
        # is now asserted, because it no longer is.
        short = foot(note="2x5")
        self.assertTrue(collect_live.looks_finished(short))
        self.assertFalse(collect_live.placeable(short))

    def test_tennis_is_collectable_even_though_it_states_no_format(self):
        """The one race sport the book never declares, and so the one it never collected.

        Every other race states its target — "7 Games Match", "Best of 3 maps". On a live
        card of 74 tennis fixtures the format note was EMPTY on 61 and read "3rd set champ
        tiebreak" on the rest; the whole MIS block is venue, surface, round, seeding and
        weather. So every fixture was refused, and four days of watching produced ten
        rows. The archive cannot cover for it either: TML's 2026 file ends on 17 January.

        What can be said truthfully is the rulebook — best-of-five is Grand Slam men's
        singles and nothing else, and TML's whole 2026 file is best_of=3 for all 137
        matches. The name list is the weaker half of the rule, so the SCORE overrides it:
        anything reaching three sets cannot be a best-of-three, whoever is playing."""
        def t(league, s1, s2):
            return collect_live.with_target(
                {"sport": 4, "kind": "target", "n": None, "s1": s1, "s2": s2,
                 "league": league, "note": "", "period": 0})

        done = t("ATP. Washington", 2, 0)
        self.assertEqual(done["n"], 2)
        self.assertTrue(collect_live.placeable(done))
        self.assertTrue(collect_live.looks_finished(done))
        self.assertEqual(collect_live.to_result(
            {**done, "p1": "A", "p2": "B", "start": 1_753_500_000}, 0)["pool"], "bo3")
        self.assertTrue(collect_live.looks_finished(t("Challenger. Samsun", 2, 1)))
        # Mid-match is still mid-match.
        self.assertFalse(collect_live.looks_finished(t("WTA. Targu Mures", 1, 1)))
        self.assertFalse(collect_live.looks_finished(t("WTA. Targu Mures", 1, 0)))
        # A Grand Slam at 2-0 is a LEAD, so it is refused here and left to the path where
        # the feed states the finish itself.
        slam = t("Wimbledon", 2, 0)
        self.assertIsNone(slam["n"])
        self.assertFalse(collect_live.placeable(slam))
        self.assertFalse(collect_live.looks_finished(slam))
        # But three sets is three sets. At Wimbledon it settles, and on a tour event it
        # says the competition was a best-of-five we did not recognise by name — which is
        # the guard that stops a mislabelled major being filed on the wrong scale.
        self.assertEqual(t("Wimbledon", 3, 1)["n"], 3)
        stray = t("Some Cup", 3, 1)
        self.assertEqual(stray["n"], 3)
        self.assertEqual(collect_live.to_result(
            {**stray, "p1": "A", "p2": "B", "start": 1_753_500_000}, 0)["pool"], "bo5")

    def test_a_goalless_match_under_way_is_remembered(self):
        """`FS` omits zeros, so 0-0 arrives as an empty score. The clock separates a
        goalless match in progress from one that has not begun — and without that, every
        0-0 was dropped, which is about one football match in twelve and a systematic tilt
        upward in the goal distribution the model reads."""
        game = {"I": 1, "O1": "A", "O2": "B", "S": 1_753_500_000,
                "SC": {"FS": {}, "CP": 2, "CPS": "2nd half", "TS": 5400, "SLS": ""}}
        rec = collect_live.snapshot(game, 1)
        self.assertIsNotNone(rec)
        self.assertEqual((rec["s1"], rec["s2"]), (0, 0))
        self.assertEqual(rec["ts"], 5400)
        self.assertTrue(collect_live.looks_finished(rec))
        # Not started: no score AND no clock.
        self.assertIsNone(collect_live.snapshot(
            {**game, "SC": {"FS": {}, "CPS": "", "TS": 0}}, 1))

    def test_a_watched_result_carries_identity_and_its_own_rating_scale(self):
        """What the watcher stores has to be usable by the generic model unchanged.

        Two details do the work. The book's participant ids survive a rename and a
        transliteration where a name does not, and a race to four sets is a different bet
        from a race to three — pooling them would rate a player on a best-of-seven scale
        off best-of-five history."""
        row = collect_live.to_result(
            {"sport": 4, "league": "Masters. Some Cup", "p1": "A", "p2": "B",
             "id1": "2778933", "id2": "4097977", "s1": 4, "s2": 2, "start": 1_753_500_000,
             "kind": "target", "n": 4}, 1_753_500_000)
        self.assertEqual(row["home_id"], "2778933")
        self.assertEqual(row["pool"], "bo7")
        self.assertEqual(row["unit"], "sets")
        self.assertEqual(row["source"], "betwinner-live")
        # And the store accepts it as it stands — no adapter-side repair on the way in.
        self.assertIsNotNone(results_store.clean(row))
        five = collect_live.to_result(
            {"sport": 4, "p1": "A", "p2": "B", "s1": 3, "s2": 1, "start": 1_753_500_000,
             "kind": "target", "n": 3, "league": "ATP. Some Open"}, 1_753_500_000)
        self.assertEqual(five["pool"], "bo5")
        # A period sport has no such split, so it stays on one scale.
        self.assertNotIn("pool", collect_live.to_result(
            {"sport": 1, "p1": "A", "p2": "B", "s1": 1, "s2": 0, "start": 1_753_500_000,
             "kind": "periods", "n": 2, "league": "E0"}, 1_753_500_000))

    def test_a_generated_competition_is_caught_without_touching_setka_cup(self):
        """A league is called generated on PHYSICAL IMPOSSIBILITY, nothing weaker.

        Two weaker signals were tried first and both flagged real competitions. Identical
        prices: six RHL fixtures were byte-identical across 35 markets, but so were four
        Setka Cup fixtures across 33 — the book templates prices for any thin market.
        A completed micro round-robin: RHL and UPVL both showed one, and so does Setka
        Cup, because that is genuinely how the circuit runs. Either rule would have
        deleted a real sport behind a real calibration.

        What separates them is whether a body could keep the schedule. Berkut Volgograd
        starts at 02:50 and again at 04:20; an ice hockey game is not over in ninety
        minutes. A round-robin's matches sit thirty minutes apart and a race format is
        done in well under that."""
        hour = 3600

        def fx(pairs, sport):
            return [(a, b, t) for a, b, t in pairs], sport

        # A three-team cycle inside ninety minutes, in a period sport (ice hockey, no
        # longer in the product's own scope but still a real sport `impossible_schedule`
        # must judge correctly for whatever the fetcher hands it — schedule physics do
        # not depend on which sports this product happens to model).
        rhl, sport = fx([("berkut", "phoenix", 0),
                         ("phoenix", "elektronik", 40 * 60),
                         ("elektronik", "berkut", 90 * 60)], 2)
        bad, why = simulated.impossible_schedule(rhl, sport)
        self.assertTrue(bad)
        self.assertIn("üretilmiş", why)

        # The SAME schedule in a race-format sport (a target of sets, not periods) is
        # ordinary — a race can finish in minutes, so tight spacing is not evidence.
        self.assertFalse(simulated.impossible_schedule(rhl, 4)[0])

        # A real group stage in a slow sport, spread over days, is fine too.
        spread = [("x", "y", 0), ("y", "z", 26 * hour), ("z", "x", 50 * hour)]
        self.assertFalse(simulated.impossible_schedule(spread, 2)[0])

        # One double-booked participant is a mislabelled fixture, not a fake league.
        single = [("p", "q", 0), ("p", "r", 30 * 60), ("s", "t", 5 * hour)]
        self.assertFalse(simulated.impossible_schedule(single, 2)[0])

        # And the flagged set survives a round trip to disk, which is how the live
        # watcher learns about it — it never sees a whole card itself.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sim.json")
            simulated.save({(2, "RHL"): "why"}, path)
            self.assertEqual(simulated.load(path), {(2, "RHL"): "why"})
        self.assertEqual(simulated.load("/nonexistent/sim.json"), {})

    def test_short_format_football_is_not_stored_as_football(self):
        """Sport 1 is not one game, and the book says so when it is not the usual one.

        A live card carries "Short Football 3x3" at two halves of five minutes,
        "Subsoccer" at 2x5, "MLS+" at 2x10 and "Student League" at 2x15, all filed under
        football, alongside China Foshan La Liga at 2x40 and ordinary football, which
        declares no format at all. They do not produce the same scorelines, and 138,835
        results of ninety-minute football teach nothing about a ten-minute one — worse,
        once stored, no row says which it was.

        The declared period length is the book telling us this is a different product. No
        declaration means the standard game, which is what real football does."""
        for note in ("2x5", "2x10", "2x12", "2 Halves of 15 minutes"):
            self.assertFalse(collect_live.real_format(1, note), note)
        for note in ("2x40", "2 halves of 40 minutes", "", None):
            self.assertTrue(collect_live.real_format(1, note), repr(note))
        # A sport with no declared minimum is unaffected — tennis notes a race, not a
        # clock, and must not be caught by a rule about period lengths.
        self.assertTrue(collect_live.real_format(4, "7 Games Match"))

        # And the guard is wired into the refusal, on both recording paths.
        short = {"sport": 1, "kind": "periods", "n": 2, "s1": 3, "s2": 2,
                 "note": "2x5", "league": "Short Football 3x3"}
        self.assertFalse(collect_live.placeable(short))
        self.assertTrue(collect_live.placeable({**short, "note": ""}))

    def test_a_missing_day_is_reported_and_a_quiet_one_is_not(self):
        """A workflow that does not run produces no failure to notice.

        On 2026-07-27 the (then daily-list) schedule never fired — not late, not at all —
        and nothing said so. A missing run looks exactly like a card where nothing cleared
        the confidence floor, and those are opposite situations: one is a real and expected
        outcome, the other means nobody got their combine. So the check asks whether
        today's OUTPUT exists, from outside, on a different schedule, because a job that
        never started cannot report anything about itself."""
        yesterday = {"2026-07-26": 1}
        # Before the day is due, silence is not evidence of anything.
        ok, _ = heartbeat.verdict(yesterday, "2026-07-27", 7, 9)
        self.assertTrue(ok)
        # After it is due and nothing was logged, say so — and say what is KNOWN rather
        # than asserting a cause this check cannot see.
        ok, msg = heartbeat.verdict(yesterday, "2026-07-27", 10, 9)
        self.assertFalse(ok)
        self.assertIn("2026-07-27", msg)
        self.assertIn("hiç çalışma kaydı yok", msg)
        self.assertIn("2026-07-26", msg)          # yesterday, for comparison
        # A day that did produce a run is not an alarm.
        ok, _ = heartbeat.verdict({**yesterday, "2026-07-27": 1}, "2026-07-27", 10, 9)
        self.assertTrue(ok)

    def test_the_slip_code_is_rebuilt_from_legs_that_have_not_started(self):
        """The combine is a document and the bet slip is a live object; they cannot share
        a lifetime. A code minted with the morning combine has lost every leg that kicked
        off before the operator opened it, and the book rebuilds what remains as an
        ACCUMULATOR — so combine.json went on citing a code for legs no longer on it.
        The refresher takes the day's combine, drops what has begun, and asks for a new
        one.

        It may never add a leg: the combine is the referee board's, and a code that
        quietly contained something they had not approved would be a different product."""
        from datetime import datetime as _dt, timezone as _tz
        now = _dt(2026, 8, 1, 12, 0, tzinfo=_tz.utc)
        combine = {"legs": [
            {"_game_id": 11, "_outcome_id": 7, "odds": 1.2,
             "_market_key": [0, "2|1.5"], "start": "2026-08-01T18:00:00+00:00"},
            # started three hours ago — gone
            {"_game_id": 12, "_outcome_id": 7, "odds": 1.3,
             "_market_key": [0, "2|1.5"], "start": "2026-08-01T09:00:00+00:00"},
            # kicks off inside the margin — treated as gone, because the book suspends a
            # market before the whistle and one late leg refuses the whole slip
            {"_game_id": 13, "_outcome_id": 7, "odds": 1.4,
             "_market_key": [0, "2|1.5"], "start": "2026-08-01T12:05:00+00:00"},
            # no betslip id: cannot be expressed as an event at all
            {"_outcome_id": 7, "odds": 1.6,
             "_market_key": [0, "2|1.5"], "start": "2026-08-01T20:00:00+00:00"},
        ]}
        got = refresh_combine.open_legs(combine, now=now)
        self.assertEqual([leg["game_id"] for leg in got], [11])
        # And when the whole day has started there is no code to give. A five-character
        # code that loads nothing is worse than no code, so the combine loses it.
        late = _dt(2026, 8, 2, 0, 0, tzinfo=_tz.utc)
        self.assertEqual(refresh_combine.open_legs(combine, now=late), [])

    def test_a_coupon_leg_carries_the_line_the_backed_side_sees(self):
        """The bet-slip event must express the line from the BACKED side's point of view.

        engine/bwfeed normalizes handicaps to the line as the HOME side sees them, so that
        both sides of one market share a key and the hold is computable. The book's slip
        wants what the feed originally published for that outcome. Backing Cuiaba +1.5 at
        1.197 and sending the stored -1.5 produced a slip the book priced at 9.00 — the
        OPPOSITE handicap, loaded silently, at a price nobody would take. That is the
        failure a one-tap slip has to be proof against, because the operator sees a code
        and not a payload."""
        away = coupon.event_of({
            "game_id": 738575246, "outcome_id": 8, "odds": 1.197,
            "market_key": (1, "2|-1.5")})
        self.assertEqual(away["Param"], 1.5)         # flipped back to the backed view
        self.assertEqual(away["GameId"], 738575246)
        home = coupon.event_of({
            "game_id": 738575246, "outcome_id": 7, "odds": 4.2,
            "market_key": (1, "2|-1.5")})
        self.assertEqual(home["Param"], -1.5)        # home side keeps the stored sign

        # Set handicaps are NOT normalized by bwfeed, so they must pass through untouched.
        sets = coupon.event_of({
            "game_id": 739350819, "outcome_id": 733, "odds": 1.25,
            "market_key": (1, "109|1.5")})
        self.assertEqual(sets["Param"], 1.5)
        # Totals have no side to flip.
        total = coupon.event_of({
            "game_id": 1, "outcome_id": 10, "odds": 1.12, "market_key": (1, "17|4.5")})
        self.assertEqual(total["Param"], 4.5)
        # Everything pre-match is Kind 3; live is a different product this never emits.
        self.assertEqual(total["Kind"], coupon.KIND_PREMATCH)

        # THE GAME ID IS `I`, NOT `CI`. A pick without it cannot become a slip event, and
        # must be dropped rather than sent with the deep-link id — the service answers
        # "events have finished" for an id it does not know, which reads like a stale card.
        self.assertIsNone(coupon.event_of({
            "outcome_id": 10, "odds": 1.12, "market_key": (1, "17|4.5")}))
        rows = bwfeed.normalize(_sample())
        self.assertTrue(any(r.get("game_id") for r in rows))
        self.assertTrue(any(r.get("game_id") != r.get("fixture_id") for r in rows))

    def test_the_slip_is_an_accumulator_and_the_page_says_so(self):
        """The shared payload cannot say "singles", and two rounds were spent believing it
        could. `Vid` looked like a clean enum — on three legs whose product was 1.4705,
        Vid=1 returned exactly that, Vid=3 returned 1.414, and Vid=2 returned 0, which is
        what a set of singles has. Pushed to forty legs the service names them itself:
        Vid=2 and Vid=4 answer "Invalid number of events in System bet" and everything
        else is stored as 1. So Vid=2 was a SYSTEM bet with no valid combination, and the
        slips shipped as "20 tekli bahis" were systems.

        This product's OWN slip is meant to load as a combine (that is the whole point),
        so what matters here is only that the code and its trim/drop accounting are
        correct — not a warning about the bet type, which the old singles-list product
        needed and this one does not."""
        picks = [{"game_id": i, "outcome_id": 10, "odds": 1.2,
                  "market_key": (0, "17|4.5")} for i in range(1, 61)]
        sent = {}

        def fake(path, body, timeout=25):
            if path == "SaveCoupon":
                sent.clear()
                sent.update(body)
                # The book's own ceiling, in its own words.
                if len(body.get("Events") or []) > coupon.MAX_EVENTS:
                    return {"Success": False,
                            "Error": "The number of events on the bet slip must not "
                                     "exceed 50"}
                return {"Success": True, "Value": "ABC12"}
            if (body.get("partner") != coupon.COUPON_PARTNER
                    and sent.get("partner") != coupon.COUPON_PARTNER):
                return {"Success": False, "Error": "Yanlış kod"}
            evs = sent.get("Events") or []
            return {"Success": True, "Value": {
                "Vid": coupon.VID_ACCUMULATOR, "Coef": 1.8, "Events": evs}}

        real, coupon._post = coupon._post, fake
        try:
            # SIXTY SELECTIONS MUST STILL PRODUCE A CODE. The book refuses the whole slip
            # past fifty rather than trimming it, so trimming here is the difference
            # between fifty legs and none. The list is in score order, so what goes is
            # its weakest end — and the detail SAYS how many were dropped.
            code, detail = coupon.create(picks)
            self.assertEqual(code, "ABC12")
            self.assertEqual(len(sent["Events"]), coupon.MAX_EVENTS)
            self.assertIn("50 bahis", detail)
            self.assertIn("10 seçim dışarıda", detail)
            self.assertEqual(sent["partner"], coupon.COUPON_PARTNER)

            # A dropped leg is REPORTED, not refused: forty-nine the operator can place
            # beats no code because one fixture kicked off.
            def lost_a_leg(path, body, timeout=25):
                out = fake(path, body, timeout)
                if path != "SaveCoupon":
                    out["Value"]["Events"] = out["Value"]["Events"][:-1]
                    out["Value"]["HasRemoveEvents"] = True
                return out

            coupon._post = lost_a_leg
            code, detail = coupon.create(picks)
            self.assertEqual(code, "ABC12")
            self.assertIn("49 bahis", detail)
            self.assertIn("alınmadı", detail)

            # A slip only its own author can open is still refused — that one is not a
            # smaller slip, it is a code that loads nothing.
            def narrow(path, body, timeout=25):
                out = fake(path, body, timeout)
                if path != "SaveCoupon" and body.get("partner") != coupon.COUPON_PARTNER:
                    return {"Success": False, "Error": "Yanlış kod"}
                return out

            coupon._post = narrow
            code, detail = coupon.create(picks)
            self.assertIsNone(code)
            self.assertIn("kendi partner", detail)
        finally:
            coupon._post = real

    def test_the_slip_obeys_the_rules_about_what_may_be_combined(self):
        """The slip loads as an accumulator, so what may not be combined is not cosmetic —
        one barred leg makes the whole thing unplaceable, and the book says so with no
        error at all. Every rule here was measured against it, not assumed."""
        sent = {}

        def responder(flags=(), keep=None):
            def fake(path, body, timeout=25):
                if path == "SaveCoupon":
                    sent.clear()
                    sent.update(body)
                    return {"Success": True, "Value": "ABC12"}
                evs = list(sent.get("Events") or [])[:keep] if keep else list(
                    sent.get("Events") or [])
                out = [dict(e, Opp1="A", Opp2="B") for e in evs]
                for i, f in flags:
                    out[i][f] = True if f != "IsRelation" else 1
                return {"Success": True, "Value": {
                    "Vid": coupon.VID_ACCUMULATOR, "Coef": 1.8, "Events": out,
                    "HasRemoveEvents": bool(keep)}}
            return fake

        real = coupon._post
        try:
            # ONE SELECTION PER EVENT. Two outcomes on one GameId come back as ONE leg
            # with HasRemoveEvents set — the book keeps the first and drops the rest
            # silently, so we would claim two and deliver one without knowing which went.
            # Deduplicated here so the count we report is the count the operator gets.
            dupes = [{"game_id": 5, "outcome_id": 9, "odds": 1.2,
                      "market_key": (0, "17|2.5")},
                     {"game_id": 5, "outcome_id": 10, "odds": 1.8,
                      "market_key": (0, "17|2.5")},
                     {"game_id": 6, "outcome_id": 9, "odds": 1.3,
                      "market_key": (0, "17|3.5")}]
            coupon._post = responder()
            code, detail = coupon.create(dupes)
            self.assertEqual(code, "ABC12")
            self.assertEqual([e["GameId"] for e in sent["Events"]], [5, 6])
            self.assertIn("aynı maçtan", detail)

            # Each of the book's own barred-leg flags refuses the code, and NAMES the leg
            # — "which one" is the question the operator will have.
            fine = [{"game_id": 1, "outcome_id": 9, "odds": 1.2, "market_key": (0, "17|2.5")},
                    {"game_id": 2, "outcome_id": 9, "odds": 1.3, "market_key": (0, "17|3.5")}]
            for flag in coupon.BANNED_FLAGS:
                coupon._post = responder(flags=[(1, flag)])
                code, detail = coupon.create(fine)
                self.assertIsNone(code, flag)
                self.assertIn("kombineye girmeyen", detail)
                self.assertIn("A / B", detail)

            # All clear is all clear.
            coupon._post = responder()
            code, _ = coupon.create(fine)
            self.assertEqual(code, "ABC12")
        finally:
            coupon._post = real

    def test_a_rung_is_denominated_in_the_unit_the_model_measures(self):
        """The ladder must offer markets counted in what the sport is SCORED in.

        Group 17 is the match total in every sport, but it counts rallies in volleyball,
        points in table tennis and frames-worth-of-points in snooker. A model fitted on
        sets cannot answer any of those, so offering group 17 to a set-scored sport builds
        a ladder whose every rung is then refused — which from the outside is
        indistinguishable from the model having no opinion.

        Reading the group right and the OUTCOME wrong fails exactly the same way: the
        over/under ids are 9/10 only inside group 17. This is engine/ladder.py's own
        sport-to-group table and is independent of which sports the live watcher currently
        tracks (tools/collect_live.py) — the ladder has to classify a market correctly for
        any sport the card carries, not only the ones this product models today."""
        def total_row(group, oid, line):
            return {"market_key": (1, f"{group}|{line}"), "outcome_id": oid,
                    "odds": 1.5, "p1": "A", "p2": "B"}

        cases = [
            (4, ladder.G_TOTAL_SETS_TENNIS, 971),    # tennis — total sets
            (6, ladder.G_TOTAL_SETS_TENNIS, 971),    # volleyball shares them
            (10, ladder.G_TOTAL_SETS_TT, 3150),      # table tennis has its own
            (30, ladder.G_TOTAL_FRAMES, 1850),       # snooker — frames
            (40, ladder.G_TOTAL_MAPS, 2824),         # esports — maps
            (1, ladder.G_TOTAL, 9),                  # football stays on 17
            (3, ladder.G_TOTAL, 9),                  # and so does basketball
        ]
        for sport, group, oid in cases:
            rows = [total_row(group, oid, "2.5"), total_row(17, 9, "180.5")]
            got = ladder.build(rows, sport, "over")
            self.assertTrue(got, f"sport {sport} built no over rung on group {group}")
            built = {int(str(r["row"]["market_key"][1]).split("|")[0]) for r in got}
            self.assertEqual(built, {group},
                             f"sport {sport} should ladder on {group}, got {built}")

        # Side rungs follow the same rule: a set-scored sport gets the SET handicap, not
        # the points one. Volleyball, badminton, padel and esports were all silently on
        # the points ladder because only tennis and table tennis were named.
        side = [{"market_key": (1, "109|1.5"), "outcome_id": 732, "odds": 1.4,
                 "p1": "A", "p2": "B"}]
        for sport in (4, 6, 16, 282):
            got = ladder.build(side, sport, "home")
            self.assertTrue(got, f"sport {sport} built no set-handicap rung")
        # And every group the ladder can now reach is still one the grader can settle.
        settleable = (set(grade.HANDICAP_GROUPS) | set(grade.TOTAL_GROUPS)
                      | set(grade.TEAM_TOTAL_GROUPS) | {1, 8, 101})
        for group in ladder.LADDER_GROUPS:
            self.assertIn(group, settleable, group)

    def test_a_result_recorded_the_other_way_round_is_swapped_not_dropped(self):
        """Which participant is "home" belongs to the SOURCE, not to the match.

        In tennis there is no home side at all, so the book's O1/O2 and a results source's
        own ordering are independent. Keying results one way silently loses matches that
        are sitting in the store.

        Losing them is the safe failure. Forgetting to swap the scores is the unsafe one:
        it settles the bet against the wrong player and reports it as a graded result."""
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "results")
            os.makedirs(store)
            with open(os.path.join(store, "4.jsonl"), "w") as f:
                f.write(json.dumps({"date": "2026-07-26", "home": "Novak Player",
                                    "away": "Marko Rival", "home_score": 3,
                                    "away_score": 1, "source": "tennisexplorer"}) + "\n")
            with mock.patch.object(results_store, "STORE", store):
                _by_id, by_name = grade_predictions.store_results(4)

        start = "2026-07-26T14:15:00+00:00"
        # Asked in the store's own order: the scores come back as stored.
        self.assertEqual(
            grade_predictions.lookup_result(by_name, "Novak Player", "Marko Rival",
                                            start, elapsed_hours=10), (3, 1))
        # Asked the other way round: found, and SWAPPED.
        self.assertEqual(
            grade_predictions.lookup_result(by_name, "Marko Rival", "Novak Player",
                                            start, elapsed_hours=10), (1, 3))
        # Which is what makes the settlement right: Rival lost by two sets, so +2.5
        # covers it and +1.5 does not.
        got = grade_predictions.lookup_result(by_name, "Marko Rival", "Novak Player",
                                              start, elapsed_hours=10)
        self.assertEqual(
            grade.settle({"market_key": (0, "109|2.5"), "outcome_id": 732}, *got),
            grade.WIN)
        self.assertEqual(
            grade.settle({"market_key": (0, "109|1.5"), "outcome_id": 732}, *got),
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
        # A tennis match can be over in well under an hour and must not wait on a football
        # clock, or a whole sport grades a day late.
        self.assertTrue(grade_predictions.finished_enough(
            4, start, "2026-07-26T21:15:00+00:00"))
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

    def test_a_results_site_names_players_differently_from_the_book(self):
        """"Fritz T." and "Taylor Harry Fritz" are the same person and neither string
        normalizes to the other, so an exact index misses every row from a source that
        abbreviates — which is every live-score site there is. Tennis had no other source
        at all, so without this bridge the sport stays permanently ungraded."""
        gp = grade_predictions
        self.assertEqual(gp.abbreviated("Fritz T."), (("fritz",), "t"))
        self.assertEqual(gp.abbreviated("Van Assche L."), (("van", "assche"), "l"))
        # A club name never ends in a lone letter, so the index this feeds stays empty for
        # football without anyone listing which sports are played by people.
        self.assertIsNone(gp.abbreviated("Manchester United"))
        self.assertIsNone(gp.abbreviated("Bahia"))

        rows = [("2026-07-27", (("fritz",), "t"), (("bergs",), "z"), 2, 0),
                ("2026-07-28", (("dellien",), "h"), (("martinez",), "p"), 2, 0)]
        self.assertEqual(gp.lookup_abbrev(rows, "Taylor Harry Fritz", "Zizou Bergs",
                                          "2026-07-27T14:00:00+00:00"), (2, 0))
        # Either way round, with the score swapped to match — there is no home player.
        self.assertEqual(gp.lookup_abbrev(rows, "Zizou Bergs", "Taylor Harry Fritz",
                                          "2026-07-27T14:00:00+00:00"), (0, 2))
        # A SPANISH DOUBLE SURNAME is why the surname is matched as a contiguous run
        # rather than as a suffix: the site prints "Martinez" for "Pedro Martinez
        # Portero", and a suffix test lost seven real matches on one card.
        self.assertEqual(gp.lookup_abbrev(rows, "Pedro Martinez Portero", "Hugo Dellien",
                                          "2026-07-28T12:00:00+00:00"), (0, 2))
        # The initial still has to agree, or every player sharing a surname matches.
        self.assertIsNone(gp.lookup_abbrev(rows, "Ricardo Fritz", "Zizou Bergs",
                                           "2026-07-27T14:00:00+00:00"))
        # And the date: these circuits replay the same pairing constantly.
        self.assertIsNone(gp.lookup_abbrev(rows, "Taylor Harry Fritz", "Zizou Bergs",
                                           "2026-07-20T14:00:00+00:00"))

    def test_a_fuzzy_result_match_refuses_the_two_ways_it_could_be_wrong(self):
        """Grading football from a source that spells clubs its own way — "Carrarese" for
        "Carrarese Calcio", "Aalesund" for "Aalesunds". It is the last route tried and the
        only one that JUDGES rather than identifies, so both of its failure modes are
        fenced: a variant is a different team, and an ambiguous name is no team at all."""
        gp = grade_predictions
        day = "2026-07-26T18:00:00+00:00"
        rows = [("2026-07-26", "Carrarese", "Napoli", 1, 3),
                ("2026-07-26", "Aalesund", "Viking", 1, 1)]
        self.assertEqual(gp.lookup_fuzzy(rows, "Napoli", "Carrarese Calcio", day), (3, 1))
        self.assertEqual(gp.lookup_fuzzy(rows, "Aalesunds", "Viking", day), (1, 1))

        # A VARIANT IS A DIFFERENT TEAM. "Corinthians Paulista (Women)" shares every
        # meaningful token with "Corinthians", and the model once priced four selections
        # off the men's side for exactly that reason. A grader repeating it would settle
        # the bet against another team's result.
        wom = [("2026-07-26", "Corinthians", "Bahia", 1, 1)]
        self.assertIsNone(gp.lookup_fuzzy(wom, "Corinthians Paulista (Women)", "Bahia", day))
        self.assertEqual(gp.lookup_fuzzy(wom, "Corinthians Paulista", "Bahia", day), (1, 1))

        # AMBIGUITY IS REFUSED OUTRIGHT. Two candidates within 0.05 mean the name does not
        # identify one fixture, and taking the higher by a hair is how a wrong result gets
        # written down as a right one. On a real card this declined 3 of 38.
        twins = [("2026-07-26", "Atletico GO", "Bahia", 1, 0),
                 ("2026-07-26", "Atletico MG", "Bahia", 0, 2)]
        self.assertIsNone(gp.lookup_fuzzy(twins, "Atletico", "Bahia", day))
        # And the date still bounds it, as everywhere else in this grader.
        self.assertIsNone(gp.lookup_fuzzy(rows, "Napoli", "Carrarese Calcio",
                                          "2026-07-20T18:00:00+00:00"))

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

    def test_the_watch_list_is_a_list_of_finish_conditions(self):
        """A sport is watched only when we can say what finishing it looks like.

        The temptation is to sweep everything the book runs and sort it out later. But
        `data/results/` feeds ratings directly, and there is no honest finish rule for a
        marble race, a card game or a simulated FIFA ladder — nor is there anything worth
        modelling in one. The watch list IS the statement of what we can settle, and today
        it is fixed at football and tennis (docs/DECISIONS/0007)."""
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
    unittest.main()
