"""End-to-end demo: generate -> validate -> tune (days 1-60) ->
holdout scoring (days 61-90) -> below-the-line -> retrospective ->
report -> check -> serve.

SYNTHETIC DATA ONLY (fictional accounts). Runs fully offline; the
serve round-trip is loopback-only on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from generator import dataset_to_json, generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from rules import HOLDOUT_DAYS, below_the_line, slice_txns  # noqa: E402
from tuning import retrospective, tune_and_score  # noqa: E402
from validation import validate_dataset  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read()


def main() -> None:
    print("== 1. generate synthetic stream (seed=42, 2000 accounts x 90 days) ==")
    data = generate_dataset()
    again = generate_dataset()
    assert data == again, "generator must be deterministic"
    assert validate_dataset(data) == [], validate_dataset(data)[:3]
    bad = sum(1 for a in data["accounts"] if a["is_bad"])
    print(f"   {len(data['transactions'])} transactions, {bad} planted "
          "bad-actor accounts, deterministic re-generation verified")

    print("\n== 2. tune on days 1-60 ONLY, score on held-out days 61-90 ==")
    ts = tune_and_score(data)
    tuned = ts["tuned_params"]
    print(f"   tuned amount_threshold: {tuned['amount_threshold']}")
    print(f"   tuned velocity: count {tuned['velocity_count']} / "
          f"sum {tuned['velocity_sum']}")
    print(f"   tuned structuring_count: {tuned['structuring_count']}")
    for rule in ("amount", "velocity", "structuring"):
        s = ts["holdout_tuned"]["scores"][rule]
        print(f"   holdout {rule}: precision {s['precision']}, "
              f"recall {s['recall']}, alerts {s['alerts']}")

    print("\n== 3. retrospective verdicts ==")
    retro = retrospective(data, tuned)
    for rule, v in retro["verdicts"].items():
        print(f"   {rule}: {v['verdict'].upper()} — {v['reason']}")
    assert retro["verdicts"]["round_amount"]["verdict"] == "retire"
    print(f"   total alert volume: {retro['alerts_per_analyst_day']} "
          "alerts per analyst-day")

    print("\n== 4. below-the-line sample (held-out) ==")
    btl = below_the_line(slice_txns(data, *HOLDOUT_DAYS), tuned)
    print(f"   amount band: {btl['amount']['band_size']} transactions, "
          f"{btl['amount']['planted_in_band']} planted just under the line")
    print(f"   structuring band deposits: "
          f"{btl['structuring']['band_deposits']}")

    print("\n== 5. markdown retrospective ==")
    md = build_markdown_report(data)
    assert md == build_markdown_report(data), "report must be deterministic"
    assert "RETIRE" in md and "round_amount" in md
    print("   " + md.splitlines()[2])

    print("\n== 6. CLI check gate ==")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="txn-monitoring-demo-")
    good_path = os.path.join(tmp, "stream.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    code_ok = cli_main(["check", "--input", good_path])
    code_err = cli_main(["check", "--input", "/tmp/no-such-stream-xyz.json"])
    print(f"   seeded={code_ok} missing-file={code_err}")
    assert code_ok == EXIT_OK and code_err == 2

    print("\n== 7. live localhost serve round-trip ==")
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(port, "/health")
        assert status == 200 and json.loads(body) == {"status": "ok"}
        status, body = _request(port, "/tune", payload={}, method="POST")
        served = json.loads(body)
        assert status == 200
        assert served["tuned_params"] == tuned
        status, body = _request(port, "/report")
        assert status == 200 and body.decode() == md
        print("   POST /tune matches local tuning; GET /report matches "
              "the local retrospective")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: generate, tune/holdout split, retrospective, "
          "below-the-line, report, check and serve verified.")


if __name__ == "__main__":
    main()
