"""CLI: exit codes, JSON shapes, and the serve round-trip."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from generator import dataset_to_json, generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from tuning import tune  # noqa: E402


def _run(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


class TestCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset(accounts=200)
        cls.tmp = tempfile.mkdtemp(prefix="txn-monitoring-test-")
        cls.path = os.path.join(cls.tmp, "stream.json")
        with open(cls.path, "w", encoding="utf-8") as fh:
            fh.write(dataset_to_json(cls.data))

    def test_generate_writes_dataset(self):
        out = os.path.join(self.tmp, "gen.json")
        self.assertEqual(_run(["generate", "--accounts", "200",
                               "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), self.data)

    def test_rules_json_shape(self):
        out = os.path.join(self.tmp, "rules.json")
        self.assertEqual(_run(["rules", "--input", self.path,
                               "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertIn("amount", payload["scores"])
        self.assertEqual(payload["holdout_days"], [61, 90])

    def test_tune_json_shape(self):
        out = os.path.join(self.tmp, "tune.json")
        self.assertEqual(_run(["tune", "--input", self.path,
                               "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["tune_days"], [1, 60])
        self.assertEqual(payload["retrospective"]["verdicts"]
                         ["round_amount"]["verdict"], "retire")

    def test_report_matches_builder(self):
        out = os.path.join(self.tmp, "report.md")
        self.assertEqual(_run(["report", "--input", self.path,
                               "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), build_markdown_report(self.data))

    def test_check_missing_file_is_error(self):
        self.assertEqual(_run(["check", "--input", "/tmp/nope-xyz.json"]),
                         EXIT_ERROR)

    def test_rules_missing_file_is_error(self):
        self.assertEqual(_run(["rules", "--input", "/tmp/nope-xyz.json"]),
                         EXIT_ERROR)


class TestCheckOnSeededFullStream(unittest.TestCase):
    def test_check_exits_zero_on_seeded_data(self):
        data = generate_dataset()
        tmp = tempfile.mkdtemp(prefix="txn-monitoring-check-")
        path = os.path.join(tmp, "full.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dataset_to_json(data))
        self.assertEqual(_run(["check", "--input", path]), EXIT_OK)


class TestServe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_dataset(accounts=200)
        reset_state(cls.data)
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        reset_state()

    def _req(self, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers,
            method="POST" if payload is not None else "GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))

    def test_tune_round_trip(self):
        status, body = self._req("/tune", payload={})
        served = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(served["tuned_params"],
                         tune(self.data)["params"])

    def test_report_round_trip(self):
        status, body = self._req("/report")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode(), build_markdown_report(self.data))

    def test_post_report_json(self):
        status, body = self._req("/report", payload={})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["report"],
                         build_markdown_report(self.data))


if __name__ == "__main__":
    unittest.main()
