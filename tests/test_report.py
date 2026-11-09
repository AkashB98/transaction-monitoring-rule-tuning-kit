"""Report + below-the-line: deterministic, contains the pinned
verdicts and the just-under-the-line estimates."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from rules import (DEFAULT_PARAMS, HOLDOUT_DAYS, below_the_line,  # noqa: E402
                   slice_txns)
from tuning import tune  # noqa: E402


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset()
        cls.md = build_markdown_report(cls.data)

    def test_deterministic(self):
        self.assertEqual(build_markdown_report(self.data), self.md)

    def test_contains_honesty_line(self):
        self.assertIn("NOT compliance-grade", self.md)
        self.assertIn("Synthetic data only", self.md)

    def test_contains_retire_verdict(self):
        self.assertIn("round_amount: RETIRE", self.md)

    def test_contains_tuned_thresholds(self):
        self.assertIn("11000.0", self.md)
        self.assertIn("alerts per analyst-day", self.md)

    def test_contains_split_language(self):
        self.assertIn("days 1-60", self.md)
        self.assertIn("days 61-90", self.md)


class TestBelowTheLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset()
        cls.tuned = tune(cls.data)["params"]

    def test_holdout_amount_band_pinned(self):
        btl = below_the_line(slice_txns(self.data, *HOLDOUT_DAYS), self.tuned)
        self.assertEqual(btl["amount"]["band_size"], 115)
        self.assertEqual(btl["amount"]["planted_in_band"], 3)
        self.assertEqual(btl["amount"]["sampled"], 23)

    def test_structuring_band_counts_deposits(self):
        btl = below_the_line(slice_txns(self.data, *HOLDOUT_DAYS), self.tuned)
        self.assertEqual(btl["structuring"]["band_deposits"], 325)
        self.assertEqual(btl["structuring"]["planted_in_band"], 145)

    def test_sample_is_every_fifth(self):
        txns = slice_txns(self.data, *HOLDOUT_DAYS)
        btl = below_the_line(txns, DEFAULT_PARAMS)
        band = [t for t in txns
                if 0.85 * 10000.0 <= t["amount"] < 10000.0]
        self.assertEqual(btl["amount"]["band_size"], len(band))
        self.assertEqual(btl["amount"]["sampled"], len(band[::5]))


if __name__ == "__main__":
    unittest.main()
