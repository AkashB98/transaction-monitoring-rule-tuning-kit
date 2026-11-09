"""No-network enforcement: with sockets blocked, generating,
validating, ruling, tuning and reporting must all still work.
(``serve`` is the only intentional exception — it binds loopback on
demand, and is not used here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from generator import generate_dataset
        from report import build_markdown_report
        from rules import DEFAULT_PARAMS, score_all, slice_txns
        from tuning import tune
        from validation import validate_dataset
        data = generate_dataset(accounts=200)
        self.assertEqual(validate_dataset(data), [])
        params = tune(data)["params"]
        scored = score_all(slice_txns(data, 61, 90), params)
        self.assertGreater(scored["total_alerts"], 0)
        self.assertIn("RETIRE", build_markdown_report(data))

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("generator", "validation", "rules", "tuning",
                    "report", "cli", "demo"):
            sys.modules.pop(mod, None)
        import cli, demo, generator, report, rules, tuning, validation  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
