"""Rules: each rule fires and does not fire where it should, scoring
is hand-verified, the noise rule never counts as a catch."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import make_dataset, txn  # noqa: E402
from rules import (DEFAULT_PARAMS, evaluate_alerts, rule_cost,  # noqa: E402
                   score_all, score_rule)


def _alerts(rows_by_account, params=None, **kw):
    data = make_dataset(rows_by_account)
    return evaluate_alerts(data["transactions"], params or DEFAULT_PARAMS,
                           **kw), data


class TestAmountRule(unittest.TestCase):
    def test_fires_at_and_above_threshold_only(self):
        alerts, _ = _alerts({"A0001": ("legit", [
            txn("T1", "A0001", 3, 9999.99),
            txn("T2", "A0001", 4, 10000.0),
            txn("T3", "A0001", 5, 15000.0)])})
        days = {a["day"] for a in alerts if a["rule"] == "amount"}
        self.assertEqual(days, {4, 5})

    def test_one_alert_per_account_day(self):
        alerts, _ = _alerts({"A0001": ("legit", [
            txn("T1", "A0001", 3, 12000.0),
            txn("T2", "A0001", 3, 13000.0)])})
        amount = [a for a in alerts if a["rule"] == "amount"]
        self.assertEqual(len(amount), 1)
        self.assertEqual(amount[0]["max_amount"], 13000.0)


class TestVelocityRule(unittest.TestCase):
    def test_count_path(self):
        rows = [txn(f"T{i}", "A0001", 2, 100.0) for i in range(10)]
        alerts, _ = _alerts({"A0001": ("legit", rows)})
        self.assertTrue(any(a["rule"] == "velocity" for a in alerts))

    def test_below_count_and_sum_does_not_fire(self):
        rows = [txn(f"T{i}", "A0001", 2, 100.0) for i in range(9)]
        alerts, _ = _alerts({"A0001": ("legit", rows)})
        self.assertFalse(any(a["rule"] == "velocity" for a in alerts))

    def test_sum_path(self):
        rows = [txn("T1", "A0001", 2, 9000.0), txn("T2", "A0001", 2, 7000.0)]
        alerts, _ = _alerts({"A0001": ("legit", rows)})
        self.assertTrue(any(a["rule"] == "velocity" for a in alerts))


class TestStructuringRule(unittest.TestCase):
    def _deposits(self, days_amounts):
        return [txn(f"T{i}", "A0001", d, amt, kind="deposit",
                    planted="structuring")
                for i, (d, amt) in enumerate(days_amounts)]

    def test_three_in_seven_days_fires(self):
        alerts, _ = _alerts({"A0001": ("bad_structuring", self._deposits(
            [(1, 9000.0), (3, 8500.0), (6, 9500.0)]))})
        self.assertTrue(any(a["rule"] == "structuring" for a in alerts))

    def test_two_in_seven_days_does_not_fire(self):
        alerts, _ = _alerts({"A0001": ("bad_structuring", self._deposits(
            [(1, 9000.0), (3, 8500.0)]))})
        self.assertFalse(any(a["rule"] == "structuring" for a in alerts))

    def test_spread_over_eight_days_does_not_fire(self):
        alerts, _ = _alerts({"A0001": ("bad_structuring", self._deposits(
            [(1, 9000.0), (5, 8500.0), (9, 9500.0)]))})
        self.assertFalse(any(a["rule"] == "structuring" for a in alerts))

    def test_below_band_does_not_count(self):
        alerts, _ = _alerts({"A0001": ("bad_structuring", self._deposits(
            [(1, 7000.0), (2, 7000.0), (3, 7000.0)]))})
        self.assertFalse(any(a["rule"] == "structuring" for a in alerts))

    def test_at_reporting_threshold_does_not_count(self):
        alerts, _ = _alerts({"A0001": ("bad_structuring", self._deposits(
            [(1, 10000.0), (2, 10000.0), (3, 10000.0)]))})
        self.assertFalse(any(a["rule"] == "structuring" for a in alerts))

    def test_salary_pattern_never_fires(self):
        # One large deposit a month: in the band, never repeated in a
        # 7-day window — the planted legitimate look-alike.
        alerts, _ = _alerts({"A0001": ("legit_salary", self._deposits(
            [(15, 9500.0), (45, 9500.0), (75, 9500.0)]))})
        self.assertFalse(any(a["rule"] == "structuring" for a in alerts))


class TestNoiseRule(unittest.TestCase):
    def test_round_amount_fires(self):
        alerts, _ = _alerts({"A0001": ("legit", [
            txn("T1", "A0001", 2, 500.0), txn("T2", "A0001", 3, 500.50)])})
        noise = [a for a in alerts if a["rule"] == "round_amount"]
        self.assertEqual([a["day"] for a in noise], [2])

    def test_noise_excluded_on_request(self):
        alerts, _ = _alerts({"A0001": ("legit", [txn("T1", "A0001", 2, 500.0)])},
                            include_noise=False)
        self.assertEqual(alerts, [])


class TestScoring(unittest.TestCase):
    def test_hand_scored_precision_recall(self):
        data = make_dataset({
            "A0001": ("bad_amount", [txn("T1", "A0001", 5, 15000.0,
                                         planted="amount")]),
            "A0002": ("bad_amount", [txn("T2", "A0002", 5, 10500.0,
                                         planted="amount")]),
            "A0003": ("legit", [txn("T3", "A0003", 5, 15000.0)]),
            "A0004": ("legit", [txn("T4", "A0004", 5, 100.0)]),
        })
        alerts = evaluate_alerts(data["transactions"],
                                 dict(DEFAULT_PARAMS,
                                      amount_threshold=11000.0),
                                 include_noise=False)
        s = score_rule(data["transactions"], alerts, "amount")
        self.assertEqual(s["true_positive_accounts"], 1)
        self.assertEqual(s["false_positive_accounts"], 1)
        self.assertEqual(s["missed_accounts"], 1)
        self.assertEqual(s["precision"], 0.5)
        self.assertEqual(s["recall"], 0.5)

    def test_noise_never_counts_as_catch(self):
        data = make_dataset({
            "A0001": ("bad_amount", [txn("T1", "A0001", 5, 500.0,
                                         planted="amount")]),
        })
        scored = score_all(data["transactions"], DEFAULT_PARAMS)
        self.assertEqual(scored["caught_accounts"], 0)
        self.assertEqual(scored["missed_cases"], 1)

    def test_cost_objective(self):
        score = {"alerts": 10, "missed_accounts": 2}
        self.assertEqual(rule_cost(score), 10 * 12 + 2 * 480)


if __name__ == "__main__":
    unittest.main()
