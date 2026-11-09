"""Generator: determinism, planted shares, look-alikes, tagging."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import archetype_counts, generate_dataset  # noqa: E402


class TestGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset()

    def test_deterministic(self):
        self.assertEqual(generate_dataset(), self.data)

    def test_shape(self):
        self.assertEqual(self.data["account_count"], 2000)
        self.assertEqual(len(self.data["accounts"]), 2000)
        self.assertEqual(len(self.data["transactions"]), 45556)
        self.assertEqual(self.data["days"], 90)

    def test_archetype_counts_pinned(self):
        self.assertEqual(archetype_counts(2000),
                         {"bad_amount": 27, "bad_velocity": 27,
                          "bad_structuring": 26, "legit_payroll": 80,
                          "legit_rent": 80, "legit_salary": 60,
                          "legit_mover": 40, "legit": 1660})

    def test_bad_share_in_planted_band(self):
        bad = sum(1 for a in self.data["accounts"] if a["is_bad"])
        self.assertEqual(bad, 80)
        share = bad / len(self.data["accounts"])
        self.assertTrue(0.03 <= share <= 0.05)

    def test_days_in_range(self):
        days = {t["day"] for t in self.data["transactions"]}
        self.assertEqual(min(days), 1)
        self.assertEqual(max(days), 90)

    def test_planted_tags_match_account_pattern(self):
        patterns = {a["account_id"]: a["pattern"]
                    for a in self.data["accounts"]}
        for t in self.data["transactions"]:
            if t["planted"] is not None:
                self.assertEqual(patterns[t["account_id"]], t["planted"])

    def test_lookalikes_are_legit(self):
        for a in self.data["accounts"]:
            if a["archetype"].startswith("legit"):
                self.assertFalse(a["is_bad"])
                self.assertIsNone(a["pattern"])

    def test_salary_never_repeats_within_a_week(self):
        salary = {a["account_id"] for a in self.data["accounts"]
                  if a["archetype"] == "legit_salary"}
        days = {}
        for t in self.data["transactions"]:
            if t["account_id"] in salary and t["amount"] >= 7500:
                days.setdefault(t["account_id"], []).append(t["day"])
        for ds in days.values():
            ds.sort()
            for a, b in zip(ds, ds[1:]):
                self.assertGreaterEqual(b - a, 7)

    def test_small_dataset_scales(self):
        small = generate_dataset(accounts=200)
        self.assertEqual(len(small["accounts"]), 200)
        self.assertEqual(len(small["transactions"]), 4599)
        self.assertEqual(sum(1 for a in small["accounts"] if a["is_bad"]), 9)

    def test_negative_accounts_rejected(self):
        with self.assertRaises(ValueError):
            generate_dataset(accounts=-1)


if __name__ == "__main__":
    unittest.main()
