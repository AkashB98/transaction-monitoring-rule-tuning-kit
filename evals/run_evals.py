"""Golden evals for transaction-monitoring-rule-tuning-kit.

SYNTHETIC DATA ONLY (fictional accounts). Every eval is
deterministic: run_evals.py writes eval_report.json and the file
must be byte-identical across runs. No timestamps, ports, or temp
paths enter the report — only names, booleans, pinned counts and
values.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_OK, load_dataset,  # noqa: E402
                 main as cli_main, make_server, reset_state)
from generator import dataset_to_json, generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from rules import HOLDOUT_DAYS, below_the_line, slice_txns  # noqa: E402
from tuning import (AMOUNT_BAND, assert_window_isolation,  # noqa: E402
                    retrospective, tune_and_score)
from validation import validate_dataset  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "fixtures", "sample_stream.json")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def main():
    print("== golden evals: transaction-monitoring-rule-tuning-kit ==")
    data = generate_dataset()
    ts = tune_and_score(data)
    tuned = ts["tuned_params"]
    retro = retrospective(data, tuned)

    # E1: generator determinism (bytes pinned)
    text1 = dataset_to_json(generate_dataset())
    text2 = dataset_to_json(generate_dataset())
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42, 2000 accounts x 90 days)",
          text1 == text2 and md5 == "0180ae54dfc8435e770801ea7bba3368",
          f"dataset_md5={md5}")

    # E2: headline counts pinned.
    bad = sum(1 for a in data["accounts"] if a["is_bad"])
    check("E2 headline counts (45556 transactions, 80 bad = 4.0%)",
          len(data["transactions"]) == 45556 and bad == 80
          and validate_dataset(data) == [],
          f"transactions={len(data['transactions'])} bad={bad}")

    # E3: tuned thresholds pinned; amount lands in the planted band.
    check("E3 tuned thresholds pinned (11000 / 14 / 20000 / 3)",
          tuned == {"amount_threshold": 11000.0, "velocity_count": 14,
                    "velocity_sum": 20000.0, "structuring_count": 3}
          and AMOUNT_BAND[0] <= tuned["amount_threshold"] <= AMOUNT_BAND[1],
          f"tuned={tuned}")

    # E4: per-rule holdout precision / recall pinned (tuned thresholds,
    # days 61-90 only — the exercise's headline numbers).
    s = ts["holdout_tuned"]["scores"]
    check("E4 holdout per-rule precision/recall pinned",
          (s["amount"]["precision"], s["amount"]["recall"]) == (0.6667, 0.9524)
          and (s["velocity"]["precision"], s["velocity"]["recall"])
          == (0.8846, 0.8846)
          and (s["structuring"]["precision"], s["structuring"]["recall"])
          == (0.3443, 1.0),
          f"amount={s['amount']['precision']}/{s['amount']['recall']} "
          f"velocity={s['velocity']['precision']}/{s['velocity']['recall']} "
          f"structuring={s['structuring']['precision']}/"
          f"{s['structuring']['recall']}")

    # E5: the split matters — velocity is perfect on its tuning window
    # and honestly worse on the holdout. Both sides pinned.
    tv = ts["tune_scores"]["scores"]["velocity"]
    hv = s["velocity"]
    check("E5 tuning window flatters velocity (1.0/1.0 -> 0.8846 holdout)",
          (tv["precision"], tv["recall"]) == (1.0, 1.0)
          and (hv["precision"], hv["recall"]) == (0.8846, 0.8846),
          f"tune={tv['precision']}/{tv['recall']} "
          f"holdout={hv['precision']}/{hv['recall']}")

    # E6: retrospective retires the noise rule, keeps the real rules.
    verdicts = {r: v["verdict"] for r, v in retro["verdicts"].items()}
    check("E6 retrospective retires round_amount, keeps real rules",
          verdicts == {"amount": "keep", "velocity": "keep",
                       "structuring": "keep", "round_amount": "retire"},
          f"verdicts={verdicts}")

    # E7: alert volume per analyst-day pinned (the workload number).
    check("E7 alert volume pinned (48.03/day total, 6.0/day real rules)",
          retro["alerts_per_analyst_day"] == 48.03
          and retro["real_alerts_per_analyst_day"] == 6.0
          and retro["verdicts"]["round_amount"]["alerts"] == 1261,
          f"per_day={retro['alerts_per_analyst_day']}")

    # E8: window isolation — overlapping tune/score windows raise.
    tune_txns = slice_txns(data, 1, 60)
    try:
        assert_window_isolation(tune_txns, tune_txns)
        overlap_raises = False
    except AssertionError:
        overlap_raises = True
    disjoint_ok = True
    try:
        assert_window_isolation(tune_txns, slice_txns(data, *HOLDOUT_DAYS))
    except AssertionError:
        disjoint_ok = False
    check("E8 tuning/scoring isolation asserted (overlap raises)",
          overlap_raises and disjoint_ok)

    # E9: below-the-line sample pinned on the holdout.
    btl = below_the_line(slice_txns(data, *HOLDOUT_DAYS), tuned)
    check("E9 below-the-line pinned (amount band 115/3, structuring 325/145)",
          btl["amount"]["band_size"] == 115
          and btl["amount"]["planted_in_band"] == 3
          and btl["structuring"]["band_deposits"] == 325
          and btl["structuring"]["planted_in_band"] == 145,
          f"amount_band={btl['amount']['band_size']} "
          f"structuring_band={btl['structuring']['band_deposits']}")

    # E10: tuning earns its keep on the holdout + case outcomes pinned.
    check("E10 tuned beats default volume on holdout (1441 vs 1605; "
          "caught 64/68)",
          ts["holdout_tuned"]["total_alerts"] == 1441
          and ts["holdout_default"]["total_alerts"] == 1605
          and ts["holdout_tuned"]["caught_accounts"] == 64
          and ts["holdout_tuned"]["missed_cases"] == 4,
          f"tuned_alerts={ts['holdout_tuned']['total_alerts']} "
          f"missed={ts['holdout_tuned']['missed_cases']}")

    # E11: CLI check exit codes 0 / 2.
    import tempfile
    tmp = tempfile.mkdtemp(prefix="txn-monitoring-evals-")
    good_path = os.path.join(tmp, "stream.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    codes = (_run_cli(["check", "--input", good_path]),
             _run_cli(["check", "--input", "/tmp/no-such-stream-xyz.json"]))
    check("E11 CLI check exit codes 0/2 (seeded passes)",
          codes == (EXIT_OK, EXIT_ERROR), f"codes={codes}")

    # E12: serve round-trip matches local tuning + report.
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=10) as resp:
            health = json.loads(resp.read())
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tune", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/report",
                                    timeout=10) as resp:
            served_report = resp.read().decode()
        serve_ok = health == {"status": "ok"} \
            and served["tuned_params"] == tuned \
            and served_report == build_markdown_report(data)
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E12 serve round-trip matches local tune + report", serve_ok)

    # E13: bundled fixture pinned (200 accounts, 4599 transactions).
    fixture = load_dataset(FIXTURE)
    check("E13 fixture pinned (200 accounts, 4599 transactions, clean)",
          fixture == generate_dataset(accounts=200)
          and len(fixture["transactions"]) == 4599
          and validate_dataset(fixture) == [],
          f"fixture_txns={len(fixture['transactions'])}")

    # E14: report determinism + the required honesty line.
    md1 = build_markdown_report(data)
    md2 = build_markdown_report(generate_dataset())
    check("E14 report determinism + honesty line",
          md1 == md2 and "NOT compliance-grade" in md1
          and "Built to learn the problem shape" in md1
          and "round_amount: RETIRE" in md1,
          f"report_md5={hashlib.md5(md1.encode()).hexdigest()}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_count = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_count,
                   "all_passed": passed == total_count, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_count} evals passed -> evals/eval_report.json")
    return 0 if passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
