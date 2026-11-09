"""Tuning: the train/holdout split is enforced, tuned values are
pinned on the seeded stream, and the retrospective retires the
noise rule."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset  # noqa: E402
from helpers import make_dataset, txn  # noqa: E402
from rules import HOLDOUT_DAYS, TUNE_DAYS, slice_txns  # noqa: E402
from tuning import (AMOUNT_BAND, assert_window_isolation,  # noqa: E402
                    retrospective, tune, tune_and_score)


class TestWindowIsolation(unittest.TestCase):
    def test_seeded_windows_are_disjoint(self):
        data = generate_dataset(accounts=200)
        tune_txns = slice_txns(data, *TUNE_DAYS)
        hold_txns = slice_txns(data, *HOLDOUT_DAYS)
        assert_window_isolation(tune_txns, hold_txns)  # must not raise
        self.assertTrue(all(t["day"] <= 60 for t in tune_txns))
        self.assertTrue(all(t["day"] >= 61 for t in hold_txns))

    def test_overlap_raises(self):
        rows = [txn("T1", "A0001", 30, 100.0), txn("T2", "A0001", 30, 200.0)]
        with self.assertRaises(AssertionError):
            assert_window_isolation(rows, rows)

    def test_partial_overlap_raises(self):
        a = [txn("T1", "A0001", 10, 100.0), txn("T2", "A0001", 55, 100.0)]
        b = [txn("T3", "A0001", 55, 100.0), txn("T4", "A0001", 80, 100.0)]
        with self.assertRaises(AssertionError):
            assert_window_isolation(a, b)


class TestTunedValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset()
        cls.ts = tune_and_score(cls.data)

    def test_tuned_params_pinned(self):
        self.assertEqual(self.ts["tuned_params"],
                         {"amount_threshold": 11000.0, "velocity_count": 14,
                          "velocity_sum": 20000.0, "structuring_count": 3})

    def test_tuned_amount_inside_planted_band(self):
        thr = self.ts["tuned_params"]["amount_threshold"]
        self.assertTrue(AMOUNT_BAND[0] <= thr <= AMOUNT_BAND[1])

    def test_holdout_scores_pinned(self):
        s = self.ts["holdout_tuned"]["scores"]
        self.assertEqual((s["amount"]["precision"], s["amount"]["recall"]),
                         (0.6667, 0.9524))
        self.assertEqual((s["velocity"]["precision"],
                          s["velocity"]["recall"]), (0.8846, 0.8846))
        self.assertEqual((s["structuring"]["precision"],
                          s["structuring"]["recall"]), (0.3443, 1.0))

    def test_tuning_flatters_velocity_holdout_corrects_it(self):
        # On the tuning window velocity scores a perfect 1.0 / 1.0;
        # the held-out window is the honest grade. Pinning both is
        # the point of the split.
        tune_v = self.ts["tune_scores"]["scores"]["velocity"]
        hold_v = self.ts["holdout_tuned"]["scores"]["velocity"]
        self.assertEqual((tune_v["precision"], tune_v["recall"]), (1.0, 1.0))
        self.assertLess(hold_v["recall"], tune_v["recall"])

    def test_tuning_reduces_holdout_alert_volume_vs_defaults(self):
        self.assertLess(self.ts["holdout_tuned"]["total_alerts"],
                        self.ts["holdout_default"]["total_alerts"])
        self.assertEqual(self.ts["holdout_default"]["total_alerts"], 1605)
        self.assertEqual(self.ts["holdout_tuned"]["total_alerts"], 1441)


class TestRetrospective(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset()
        tuned = tune(cls.data)
        cls.retro = retrospective(cls.data, tuned["params"])

    def test_noise_rule_retired(self):
        self.assertEqual(self.retro["verdicts"]["round_amount"]["verdict"],
                         "retire")

    def test_real_rules_kept(self):
        for rule in ("amount", "velocity", "structuring"):
            self.assertEqual(self.retro["verdicts"][rule]["verdict"], "keep")

    def test_alert_volume_per_analyst_day_pinned(self):
        self.assertEqual(self.retro["alerts_per_analyst_day"], 48.03)
        self.assertEqual(self.retro["real_alerts_per_analyst_day"], 6.0)
        self.assertEqual(
            self.retro["verdicts"]["round_amount"]
            ["alerts_per_analyst_day"], 42.03)

    def test_tiny_dataset_still_tunes(self):
        data = make_dataset({
            "A0001": ("bad_amount", [txn("T1", "A0001", 5, 15000.0,
                                         planted="amount")]),
            "A0002": ("legit", [txn("T2", "A0002", 5, 100.0)]),
        })
        result = tune(data)
        self.assertIn("amount_threshold", result["params"])


if __name__ == "__main__":
    unittest.main()
