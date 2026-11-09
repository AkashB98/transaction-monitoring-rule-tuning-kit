"""Validation: clean streams pass, planted defects are reported."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset  # noqa: E402
from validation import validate_dataset  # noqa: E402


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset(accounts=200)

    def test_generated_stream_is_clean(self):
        self.assertEqual(validate_dataset(self.data), [])

    def test_fixture_is_clean(self):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "fixtures", "sample_stream.json")
        with open(path, encoding="utf-8") as fh:
            fixture = json.load(fh)
        self.assertEqual(validate_dataset(fixture), [])
        self.assertEqual(fixture, generate_dataset(accounts=200))

    def test_not_an_object(self):
        self.assertEqual(validate_dataset([]),
                         ["dataset must be a JSON object"])

    def test_duplicate_txn_id(self):
        bad = copy.deepcopy(self.data)
        bad["transactions"][1]["txn_id"] = bad["transactions"][0]["txn_id"]
        self.assertTrue(any("duplicate txn_id" in i
                            for i in validate_dataset(bad)))

    def test_unknown_account(self):
        bad = copy.deepcopy(self.data)
        bad["transactions"][0]["account_id"] = "A9999"
        self.assertTrue(any("unknown account_id" in i
                            for i in validate_dataset(bad)))

    def test_day_out_of_range(self):
        bad = copy.deepcopy(self.data)
        bad["transactions"][0]["day"] = 91
        self.assertTrue(any("bad day" in i for i in validate_dataset(bad)))

    def test_negative_amount(self):
        bad = copy.deepcopy(self.data)
        bad["transactions"][0]["amount"] = -5.0
        self.assertTrue(any("bad amount" in i for i in validate_dataset(bad)))

    def test_bad_kind(self):
        bad = copy.deepcopy(self.data)
        bad["transactions"][0]["kind"] = "transfer"
        self.assertTrue(any("bad kind" in i for i in validate_dataset(bad)))

    def test_bad_archetype(self):
        bad = copy.deepcopy(self.data)
        bad["accounts"][0]["archetype"] = "whale"
        self.assertTrue(any("bad archetype" in i
                            for i in validate_dataset(bad)))


if __name__ == "__main__":
    unittest.main()
