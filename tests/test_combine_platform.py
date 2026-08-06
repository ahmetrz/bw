"""Regression tests for the new combine-platform layer: engine/dataquality.py,
engine/confidence.py, engine/referee.py, engine/combine.py, engine/governance.py.

Kept in its OWN file rather than added to tests/test_regression.py deliberately: that
file anchors the live scan/daily-picks pipeline that .github/workflows already depend on
every day, and this platform is additive to it (docs/DECISIONS/0001) — a failure in one
suite must never look like a failure in the other when read from CI output.

    python -m unittest discover -s tests -v
"""
import datetime
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from engine import combine, confidence, dataquality, governance, grade, rating, referee  # noqa: E402

NOW = datetime.datetime(2026, 8, 6, 12, 0, tzinfo=datetime.timezone.utc)


def leg(i, sport_id, league, conf_pct, odds, n=8000, name_match=1.0, needs_conf=False,
       start=None, market_type="moneyline"):
    # `start` as an ISO STRING, matching engine/bwfeed.py's real row shape — a datetime
    # object here would hide the exact bug this fixture caught once already (combine.py
    # comparing a string straight against a datetime and crashing in production).
    start = start or (NOW + datetime.timedelta(hours=3))
    if isinstance(start, datetime.datetime):
        start = start.isoformat()
    base = {
        "p1": f"Takim{i}A", "p2": f"Takim{i}B", "p1_id": f"{i}a", "p2_id": f"{i}b",
        "sport_id": sport_id, "match_id": i, "fixture_id": i, "league": league,
        "start": start, "odds": odds,
        "model_survival": conf_pct / 100.0, "name_match": name_match,
        "division_matches": n, "model_n": n, "market_type": market_type,
        "settlement": {"needs_confirmation": needs_conf, "scope": "match"},
        "staleness_seconds": 60, "direction": "home", "ladder_available": 3,
        "model_source": "elo" if sport_id == 1 else "generic",
    }
    base.update(rating.score(base, floor=0.75))
    return base


def annotated(picks):
    confidence.annotate(picks)
    return picks


class TestDataQuality(unittest.TestCase):
    def test_reason_codes_are_from_the_fixed_vocabulary(self):
        vocab = {dataquality.CRITICAL_ODDS_MISSING, dataquality.STALE_EVENT_DATA,
                dataquality.PLAYER_IDENTITY_UNCERTAIN, dataquality.INSUFFICIENT_SAMPLE,
                dataquality.MARKET_MAPPING_UNVERIFIED, dataquality.LINEUP_DATA_UNAVAILABLE,
                dataquality.SOURCE_CONFLICT, dataquality.RESULT_VERIFICATION_UNAVAILABLE}
        p = leg(1, 1, "Test Ligi", 85, 1.5, n=50, name_match=0.83)
        dq = dataquality.assess(p)
        for r in dq["reasons"]:
            self.assertIn(r["code"], vocab, f"unknown reason code {r['code']!r}")

    def test_missing_odds_is_critical_and_blocks_combine(self):
        p = leg(1, 1, "Test Ligi", 90, 1.5)
        p["odds"] = None
        dq = dataquality.assess(p)
        self.assertTrue(dq["blocks_combine"])
        self.assertEqual(dq["score"], 0.0)

    def test_thin_sample_lowers_score_but_does_not_fabricate_it(self):
        strong = dataquality.assess(leg(1, 1, "L", 90, 1.5, n=8000))
        weak = dataquality.assess(leg(2, 1, "L", 90, 1.5, n=50))
        self.assertGreater(strong["score"], weak["score"])
        self.assertFalse(weak["blocks_combine"], "a thin sample flags, it does not veto by itself")

    def test_structural_gaps_are_always_disclosed(self):
        dq = dataquality.assess(leg(1, 1, "L", 90, 1.5))
        codes = {r["code"] for r in dq["reasons"]}
        self.assertIn(dataquality.LINEUP_DATA_UNAVAILABLE, codes)
        self.assertIn(dataquality.SOURCE_CONFLICT, codes)


class TestConfidence(unittest.TestCase):
    def test_confidence_score_equals_ratings_score_exactly(self):
        """hard rule 6 extended into the new layer: confidence.py must not recompute the
        0-100 score differently from engine/rating.py — it wraps the same number."""
        p = leg(1, 1, "L", 88, 1.6, n=9000)
        conf = confidence.build(p)
        self.assertEqual(conf["confidence_score"], p["score"])

    def test_score_never_reads_the_price_through_confidence_either(self):
        base = leg(1, 1, "L", 90, 1.5, n=9000)
        want = confidence.build(base)["confidence_score"]
        for odds in (1.10, 1.85, 4.40, 17.0):
            priced = dict(base, odds=odds)
            priced.update(rating.score(priced, floor=0.75))
            got = confidence.build(priced)["confidence_score"]
            self.assertEqual(got, want, "confidence score moved when only price changed")

    def test_ev_and_implied_probability_are_reported_not_fabricated(self):
        p = leg(1, 1, "L", 90, 1.6, n=9000)
        conf = confidence.build(p)
        self.assertAlmostEqual(conf["implied_probability"], 1 / 1.6, places=4)
        self.assertIsNotNone(conf["expected_value"])
        # corrected_probability requires a non-proportional de-vig method this codebase
        # does not implement (DATA_CONTRACT.md) — must stay None, never a guessed number.
        self.assertIsNone(conf["corrected_probability"])

    def test_annotate_attaches_in_place(self):
        picks = [leg(1, 1, "L", 90, 1.5), leg(2, 4, "L2", 85, 1.4)]
        confidence.annotate(picks)
        for p in picks:
            self.assertIn("_confidence", p)
            self.assertEqual(p["_confidence"]["confidence_score"], p["score"])


class TestRefereeBoard(unittest.TestCase):
    def test_overfitting_judge_vetoes_near_certainty_on_a_thin_sample(self):
        """The exact shape of two real bugs this codebase already shipped once
        (basketball's sign error at 90.4%, table tennis's 97% extrapolation)."""
        p = leg(1, 1, "L", 98, 1.15, n=80)   # model_survival ~0.98, n=80
        conf = confidence.build(p)
        v = referee.overfitting_judge(p, conf, {})
        self.assertEqual(v["verdict"], referee.VETO)

    def test_odds_ev_judge_vetoes_below_min_odds(self):
        p = leg(1, 1, "L", 90, 1.05)
        conf = confidence.build(p)
        v = referee.odds_ev_judge(p, conf, {})
        self.assertEqual(v["verdict"], referee.VETO)

    def test_odds_ev_judge_flags_implausible_ev_as_suspicious_not_good(self):
        p = leg(1, 1, "L", 90, 4.0, n=9000)   # model says 90% survival at odds 4.0
        conf = confidence.build(p)
        v = referee.odds_ev_judge(p, conf, {})
        self.assertEqual(v["verdict"], referee.FLAG)
        self.assertIn("model/veri hatasına işaret eder", v["note"])

    def test_result_verifiability_judge_vetoes_unverifiable_sport(self):
        p = leg(1, 9999, "L", 90, 1.5)   # sport with no results_store coverage at all
        conf = confidence.build(p)
        v = referee.result_verifiability_judge(p, conf, {})
        self.assertEqual(v["verdict"], referee.VETO)

    def test_correlation_judge_flags_league_concentration(self):
        picks = [leg(i, 1, "Ayni Lig", 88, 1.5) for i in range(1, 5)]
        confs = [p["score"] for p in annotated(picks)]
        result = referee.correlation_judge(picks, confs, {})
        self.assertTrue(result["notes"])
        self.assertEqual(set(result["flagged_indices"]), {0, 1, 2, 3})

    def test_final_risk_judge_excludes_any_leg_with_a_veto(self):
        picks = annotated([leg(1, 1, "L", 90, 1.05)])   # odds below MIN_ODDS -> veto
        per_leg, corr, final = referee.review_all(picks, [picks[0]["_confidence"]], {})
        self.assertFalse(final["decisions"][0]["include"])
        self.assertEqual(final["eligible_count"], 0)


class TestCombineOptimizer(unittest.TestCase):
    def _card(self):
        return annotated([
            leg(1, 1, "Premier League", 92, 1.30),
            leg(2, 1, "Premier League", 90, 1.35),
            leg(3, 4, "ATP Rome", 88, 1.45),
            leg(4, 4, "WTA Madrid", 85, 1.55),
            leg(5, 1, "La Liga", 81, 1.80),
            leg(6, 10, "Setka Cup", 95, 1.20),          # wrong sport
            leg(7, 1, "Serie A", 79, 1.90),              # below 80
        ])

    def test_scope_is_football_and_tennis_only(self):
        report = combine.build_combine(self._card(), NOW)
        sports = {l["sport_id"] for l in report["legs"]}
        self.assertTrue(sports.issubset(config.COMBINE_SPORTS))
        excluded_matches = {g["match"] for g in report["gate_excluded"]}
        self.assertIn("Takim6A v Takim6B", excluded_matches)

    def test_min_confidence_80_is_enforced(self):
        report = combine.build_combine(self._card(), NOW)
        for leg_ in report["legs"]:
            self.assertGreaterEqual(leg_["_confidence"]["confidence_score"],
                                    config.MIN_COMBINE_CONFIDENCE)
        excluded_matches = {g["match"] for g in report["gate_excluded"]}
        self.assertIn("Takim7A v Takim7B", excluded_matches)

    def test_one_selection_per_match_in_the_final_combine(self):
        picks = annotated([leg(1, 1, "L", 90, 1.4), leg(1, 1, "L", 88, 1.5)])
        # both legs share match_id=1 on purpose
        chosen = combine.optimize(picks)
        match_ids = {l.get("match_id") for l in chosen}
        self.assertLessEqual(len(chosen), 1, "two legs from the same match were combined")

    def test_no_forced_combine_when_nothing_qualifies(self):
        picks = annotated([leg(1, 1, "L", 79, 1.5), leg(2, 4, "L2", 70, 1.4)])
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)
        self.assertEqual(report["legs"], [])
        self.assertTrue(report["why"])

    def test_no_forced_combine_when_everything_is_vetoed(self):
        picks = annotated([leg(1, 1, "L", 98, 1.15, n=80)])   # trips overfitting veto
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)

    def test_eligible_handles_string_start_timestamps_without_crashing(self):
        """Real picks (engine/bwfeed.py) always carry `start` as an ISO STRING, never a
        datetime object — a comparison bug here (string <= datetime) crashed the whole
        combine build the first time this was run against realistic data, and every unit
        test had been passing datetime objects instead, which hid it completely."""
        picks = annotated([leg(1, 1, "L", 90, 1.4,
                              start=(NOW + datetime.timedelta(hours=3)).isoformat())])
        report = combine.build_combine(picks, NOW)   # must not raise
        self.assertEqual(report["leg_count"], 1)

    def test_unparseable_start_excludes_rather_than_crashes(self):
        picks = annotated([leg(1, 1, "L", 90, 1.4, start="not-a-real-timestamp")])
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)
        self.assertIn("başlangıç zamanı okunamadı", report["gate_excluded"][0]["reasons"][0])

    def test_missing_odds_directly_excludes_a_leg(self):
        """Invariant 7 (section 24): a selection with no odds at all cannot enter the
        combine — distinct from odds below MIN_ODDS, which is a different gate."""
        picks = annotated([leg(1, 1, "L", 90, 1.5)])
        picks[0]["odds"] = None
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)

    def test_critical_data_quality_directly_excludes_a_leg(self):
        """Invariant 5 (section 24): a selection with critically-missing data cannot
        enter the combine, independent of its confidence score."""
        picks = annotated([leg(1, 1, "L", 95, 1.5)])
        picks[0]["_confidence"]["data_quality"]["blocks_combine"] = True
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)

    def test_uncertain_settlement_is_never_marked_certain(self):
        """Invariant 10 (section 24): a market whose settlement rule is not confirmed
        must carry needs_confirmation=True through to the combine's own settlement —
        pushed/half legs, where Betwinner's multi-leg convention is unverified
        (engine/settlement.py OPEN_QUESTIONS), must never be reported as certain."""
        legs_graded = [{"result": grade.WIN, "odds": 1.5},
                       {"result": grade.HALF, "odds": 2.0}]
        out = combine.settle_combine(legs_graded)
        self.assertTrue(out["needs_confirmation"])
        # A combine with every leg a clean win/loss (no push/half) IS certain.
        clean = [{"result": grade.WIN, "odds": 1.5}, {"result": grade.LOSS, "odds": 1.4}]
        self.assertFalse(combine.settle_combine(clean)["needs_confirmation"])

    def test_started_matches_are_excluded(self):
        picks = annotated([leg(1, 1, "L", 90, 1.5, start=NOW - datetime.timedelta(minutes=5))])
        report = combine.build_combine(picks, NOW)
        self.assertEqual(report["leg_count"], 0)
        self.assertIn("başlamış", report["gate_excluded"][0]["reasons"][0])

    def test_combined_probability_is_the_product_of_leg_probabilities(self):
        picks = annotated([leg(1, 1, "L1", 90, 1.4), leg(2, 4, "L2", 88, 1.5)])
        report = combine.build_combine(picks, NOW)
        if report["leg_count"] == 2:
            self.assertAlmostEqual(report["combined_probability"], 0.90 * 0.88, places=4)

    def test_optimizer_never_drops_combined_probability_below_the_floor(self):
        picks = annotated([leg(i, 1, f"L{i}", 81, 1.9) for i in range(1, 10)])
        chosen = combine.optimize(picks)
        self.assertGreaterEqual(combine._combined_probability(chosen),
                                config.MIN_COMBINE_COMBINED_PROBABILITY)

    def test_reproducible_given_the_same_input(self):
        report1 = combine.build_combine(self._card(), NOW)
        report2 = combine.build_combine(self._card(), NOW)
        self.assertEqual([l["p1"] for l in report1["legs"]],
                         [l["p1"] for l in report2["legs"]])


class TestCombineSettlement(unittest.TestCase):
    def test_any_loss_zeroes_the_whole_combine(self):
        legs = [{"result": grade.WIN, "odds": 1.5}, {"result": grade.LOSS, "odds": 1.4}]
        self.assertEqual(combine.settle_combine(legs), {
            "result": grade.LOSS, "multiplier": 0.0, "needs_confirmation": False})

    def test_push_is_removed_from_the_odds_product(self):
        legs = [{"result": grade.WIN, "odds": 2.0}, {"result": grade.PUSH, "odds": 1.8}]
        out = combine.settle_combine(legs)
        self.assertEqual(out["result"], grade.WIN)
        self.assertAlmostEqual(out["multiplier"], 2.0)   # push contributes x1.0, not x1.8
        self.assertTrue(out["needs_confirmation"])

    def test_half_leg_contributes_the_average_of_win_and_push(self):
        legs = [{"result": grade.HALF, "odds": 2.0}]
        out = combine.settle_combine(legs)
        self.assertAlmostEqual(out["multiplier"], (2.0 + 1.0) / 2.0)

    def test_any_pending_leg_makes_the_whole_combine_pending(self):
        legs = [{"result": grade.WIN, "odds": 1.5}, {"result": None, "odds": 1.4}]
        out = combine.settle_combine(legs)
        self.assertEqual(out["result"], "pending")
        self.assertIsNone(out["multiplier"])


class TestTrackRecord(unittest.TestCase):
    def _write_log(self, rows):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for r in rows:
            tmp.write(json.dumps(r) + "\n")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        return tmp.name

    def test_brier_score_is_zero_for_perfect_confident_predictions(self):
        from engine import track_record
        path = self._write_log([
            {"model_pct": 100.0, "result": "win", "sport_id": 1},
            {"model_pct": 100.0, "result": "win", "sport_id": 1},
        ])
        out = track_record.brier_score(path)
        self.assertAlmostEqual(out["overall"], 0.0)

    def test_brier_score_penalises_confident_wrong_predictions(self):
        from engine import track_record
        path = self._write_log([{"model_pct": 95.0, "result": "loss", "sport_id": 1}])
        out = track_record.brier_score(path)
        self.assertAlmostEqual(out["overall"], 0.95 ** 2)

    def test_log_loss_matches_coin_flip_baseline_at_50_percent(self):
        from engine import track_record
        import math
        path = self._write_log([
            {"model_pct": 50.0, "result": "win", "sport_id": 1},
            {"model_pct": 50.0, "result": "loss", "sport_id": 1},
        ])
        out = track_record.log_loss(path)
        self.assertAlmostEqual(out, math.log(2), places=3)

    def test_calibration_by_sport_requires_min_meaningful_samples(self):
        from engine import track_record
        rows = [{"model_pct": 90.0, "result": "win", "sport_id": 1} for _ in range(5)]
        path = self._write_log(rows)
        self.assertEqual(track_record.calibration_by_sport(path), {})


class TestGovernance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_path = governance.PROPOSALS_PATH
        governance.PROPOSALS_PATH = os.path.join(self._tmp.name, "proposed_changes.jsonl")

    def tearDown(self):
        governance.PROPOSALS_PATH = self._orig_path
        self._tmp.cleanup()

    def test_propose_never_auto_applies(self):
        rec = governance.propose(
            "pmc-test-1", "threshold_change", "test", "test", {"x": 1},
            current_value=0.75, proposed_value=0.80)
        self.assertEqual(rec["status"], governance.STATUS_PROPOSED)
        proposals = governance.list_proposals(status=governance.STATUS_PROPOSED)
        self.assertEqual(len(proposals), 1)
        # Nothing in this module ever flips status without an explicit review() call.
        self.assertEqual(governance.list_proposals()[0]["status"], governance.STATUS_PROPOSED)

    def test_review_requires_an_explicit_human_decision(self):
        governance.propose("pmc-test-2", "weight_change", "t", "t", {})
        with self.assertRaises(ValueError):
            governance.review("pmc-test-2", "maybe", "operator")
        rec = governance.review("pmc-test-2", governance.STATUS_APPROVED, "operator",
                                note="looks right")
        self.assertEqual(rec["status"], governance.STATUS_APPROVED)
        self.assertEqual(rec["reviewed_by"], "operator")

    def test_unknown_category_is_rejected(self):
        with self.assertRaises(ValueError):
            governance.propose("pmc-test-3", "not_a_real_category", "t", "t", {})

    def test_model_version_archive_is_safe_when_nothing_to_archive(self):
        result = governance.archive_model_version(999999)
        self.assertIsNone(result)


class TestPdfReport(unittest.TestCase):
    """reportlab is the one dependency this project takes (requirements.txt) — skipped
    cleanly if it is not installed, rather than failing the whole suite, since the core
    scanning pipeline must keep working with zero pip installs (README.md)."""

    @classmethod
    def setUpClass(cls):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("reportlab not installed — pip install -r requirements.txt")

    def _combine_payload(self, leg_count):
        legs = [{"match": f"Takim{i}A v Takim{i}B", "selection_tr": "1", "sport": "Futbol",
                "league": "L", "start": "2026-08-06T15:00:00+00:00", "odds": 1.5,
                "confidence": {"confidence_score": 88.0, "data_quality": {"score": 90.0},
                              "factors": {"up": [], "down": []}, "risks": []},
                "referee": {"verdicts": []}}
               for i in range(leg_count)]
        return {"date": "2026-08-06", "generated_at": "2026-08-06T12:00:00+00:00",
               "leg_count": leg_count, "legs": legs, "combined_odds": 1.5 ** leg_count,
               "combined_probability": 0.85 ** leg_count if leg_count else None,
               "combined_probability_band": {"low": 0.5, "high": 0.9},
               "avg_confidence": 88.0, "scanned_count": 10, "eligible_count": leg_count,
               "referee_approved_count": leg_count, "coupon_code": "AB12C" if leg_count else None,
               "coupon_detail": "", "borderline": [], "vetoed": [],
               "why": "3 seçim seçildi" if leg_count else "aday yok",
               "min_combine_confidence": 80.0, "gate_excluded": []}

    def test_pdf_builds_for_a_produced_combine(self):
        from tools import make_pdf_report
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "combine.json")
            out = os.path.join(tmp, "report.pdf")
            with open(inp, "w") as f:
                json.dump(self._combine_payload(3), f)
            make_pdf_report.build(inp, out)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 1000, "PDF suspiciously small/empty")
            with open(out, "rb") as f:
                self.assertEqual(f.read(4), b"%PDF", "not a valid PDF header")

    def test_pdf_builds_for_no_combine_today(self):
        from tools import make_pdf_report
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "combine.json")
            out = os.path.join(tmp, "report.pdf")
            with open(inp, "w") as f:
                json.dump(self._combine_payload(0), f)
            make_pdf_report.build(inp, out)
            self.assertTrue(os.path.exists(out))
            with open(out, "rb") as f:
                self.assertEqual(f.read(4), b"%PDF")

    def test_turkish_characters_render_via_the_vendored_font(self):
        """The specific bug class this test exists for: reportlab's built-in Helvetica
        uses WinAnsi encoding, which is MISSING ğ, ı and ş — a Turkish-language PDF built
        on it would silently drop or mis-render those exact characters."""
        from reportlab.pdfbase import pdfmetrics
        from tools import make_pdf_report
        make_pdf_report._register_fonts()
        font = pdfmetrics.getFont("DejaVu")
        for ch in "çğışöüÇĞİŞÖÜ":
            width = font.stringWidth(ch, 10)
            self.assertGreater(width, 0, f"{ch!r} has no glyph width — font is missing it")


class TestLogImmutability(unittest.TestCase):
    def test_grade_combine_only_ever_changes_the_settlement_field(self):
        """Invariant 8 (section 24), applied to the new log: tools/grade_combine.py may
        fill in `settlement` (and per-leg `result`/`final_score`/`graded_via`, which are
        OUTCOME fields, not selection fields) but must never alter what was actually
        picked — the odds, the market, the confidence at selection time."""
        from unittest import mock
        from engine import results_store
        from tools import grade_combine

        original_leg = {"sport_id": 1, "p1": "Alfa", "p2": "Beta", "p1_id": "111",
                        "p2_id": "222", "start": "2026-08-06T10:00:00+00:00", "odds": 1.5,
                        "_market_key": [12345, "1|None"], "_outcome_id": 1,
                        "selection_tr": "1 (ev sahibi kazanır)"}
        synthetic = {1: [{"date": "2026-08-06", "home": "Alfa", "away": "Beta",
                          "home_score": 2, "away_score": 0, "home_id": "111",
                          "away_id": "222", "source": "betwinner-live"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "combine_log.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"date": "2026-08-06", "leg_count": 1,
                                    "combined_odds": 1.5, "why": "1 seçim seçildi",
                                    "legs": [dict(original_leg)],
                                    "settlement": None}) + "\n")
            with mock.patch.object(results_store, "load",
                                   side_effect=lambda sid: synthetic.get(sid, [])):
                now = datetime.datetime(2026, 8, 6, 14, 0, tzinfo=datetime.timezone.utc)
                grade_combine.grade_all(path, now=now)
            with open(path) as f:
                out = json.loads(f.readline())
        for key, val in original_leg.items():
            self.assertEqual(out["legs"][0][key], val,
                             f"selection field {key!r} was altered during grading")
        self.assertEqual(out["combined_odds"], 1.5)
        self.assertEqual(out["why"], "1 seçim seçildi")
        self.assertIsNotNone(out["settlement"])


class TestGradeCombine(unittest.TestCase):
    def test_settles_a_combine_end_to_end_against_a_stored_result(self):
        from unittest import mock
        from engine import results_store
        from tools import grade_combine

        synthetic = {1: [{"date": "2026-08-06", "home": "Alfa", "away": "Beta",
                          "home_score": 2, "away_score": 0, "home_id": "111",
                          "away_id": "222", "source": "betwinner-live"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "combine_log.jsonl")
            leg = {"sport_id": 1, "p1": "Alfa", "p2": "Beta", "p1_id": "111",
                  "p2_id": "222", "start": "2026-08-06T10:00:00+00:00", "odds": 1.5,
                  "_market_key": [12345, "1|None"], "_outcome_id": 1}
            with open(path, "w") as f:
                f.write(json.dumps({"date": "2026-08-06", "legs": [leg],
                                    "settlement": None}) + "\n")
                f.write(json.dumps({"date": "2026-08-05", "legs": [],
                                    "settlement": None}) + "\n")

            with mock.patch.object(results_store, "load",
                                   side_effect=lambda sid: synthetic.get(sid, [])):
                now = datetime.datetime(2026, 8, 6, 14, 0, tzinfo=datetime.timezone.utc)
                grade_combine.grade_all(path, now=now)

            with open(path) as f:
                out = [json.loads(l) for l in f]
        by_date = {r["date"]: r["settlement"] for r in out}
        self.assertEqual(by_date["2026-08-06"], {"result": "win", "multiplier": 1.5,
                                                  "needs_confirmation": False})
        self.assertEqual(by_date["2026-08-05"]["result"], "no_bet")

    def test_a_combine_with_one_ungraded_leg_stays_pending(self):
        from unittest import mock
        from engine import results_store
        from tools import grade_combine

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "combine_log.jsonl")
            leg = {"sport_id": 1, "p1": "NoSuchTeam", "p2": "AlsoUnknown",
                  "p1_id": "999", "p2_id": "888",
                  "start": "2026-08-06T10:00:00+00:00", "odds": 1.5,
                  "_market_key": [12345, "1|None"], "_outcome_id": 1}
            with open(path, "w") as f:
                f.write(json.dumps({"date": "2026-08-06", "legs": [leg],
                                    "settlement": None}) + "\n")
            with mock.patch.object(results_store, "load", return_value=[]):
                now = datetime.datetime(2026, 8, 6, 14, 0, tzinfo=datetime.timezone.utc)
                grade_combine.grade_all(path, now=now)
            with open(path) as f:
                out = [json.loads(l) for l in f]
        self.assertIsNone(out[0]["settlement"])


class TestPlatformPages(unittest.TestCase):
    def test_combine_page_escapes_hostile_team_names(self):
        """Team names come from the feed. tests/test_regression.py already checks this
        discipline for picks.html/results.html; the new screens need the same guarantee
        independently, since tools/webshell.py is a SEPARATE escaping path."""
        from tools import daily_combine, make_platform_pages as mpp

        picks = annotated([leg(1, 1, "L", 90, 1.5)])
        picks[0]["p1"] = '<script>alert(1)</script>'
        picks[0]["p2"] = 'O"Brien & Sons'
        report = combine.build_combine(picks, NOW)
        public = dict(report)
        public["legs"] = [daily_combine.serialize_leg(p, "betwinner2.com")
                          for p in report["legs"]]
        for key in ("coupon_code", "coupon_detail", "date", "min_combine_confidence"):
            public.setdefault(key, None)

        page = mpp.render_combine(public)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('"onerror="', page)

    def test_no_external_resources_in_any_new_page(self):
        from tools import make_platform_pages as mpp
        pages = [mpp.render_combine(None), mpp.render_referee(None),
                mpp.render_dataquality(None), mpp.render_scanned(None),
                mpp.render_rejected(None), mpp.render_lab(None, None, {}, {}),
                mpp.render_calibration({}), mpp.render_model_versions(set()),
                mpp.render_proposed_changes([]), mpp.render_source_health(None),
                mpp.render_runs([], []), mpp.render_settings()]
        for page in pages:
            for external in ("http://", "<script src", "<link"):
                self.assertNotIn(external, page)

    def test_empty_states_render_without_crashing(self):
        """Every page must handle 'no data yet' — a fresh clone has none of this data."""
        from tools import make_platform_pages as mpp
        mpp.render_combine(None)
        mpp.render_referee(None)
        mpp.render_combine_history([], "history")
        mpp.render_combine_history([], "results")


if __name__ == "__main__":
    unittest.main()
