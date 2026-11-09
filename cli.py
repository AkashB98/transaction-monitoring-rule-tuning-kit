"""CLI: generate | rules | tune | report | check | demo | serve.

SYNTHETIC DATA ONLY — every account is fictional and every dataset
handled here is fabricated sample data. NOT compliance-grade tooling.

Exit codes:
  check : 0 = pass, 1 = quality breach (a real rule below its holdout
          floor, or the noise rule not retired), 2 = usage / IO /
          data-quality error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_dataset, dataset_to_json  # noqa: E402
from report import build_markdown_report  # noqa: E402
from rules import (DEFAULT_PARAMS, HOLDOUT_DAYS, REAL_RULES,  # noqa: E402
                   score_all, slice_txns)
from tuning import retrospective, tune_and_score  # noqa: E402
from validation import validate_dataset  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
MIN_HOLDOUT_RECALL = 0.4


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def load_dataset(path: str) -> Dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("dataset file must contain a JSON object")
    return data


def _load_or_error(path: str) -> Optional[Dict]:
    try:
        return load_dataset(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _validated(args):
    data = _load_or_error(args.input)
    if data is None:
        return None, EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}", file=sys.stderr)
        return None, EXIT_ERROR
    return data, EXIT_OK


def _write_out(args, text: str, summary: str) -> int:
    if getattr(args, "out", None):
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(summary)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_generate(args) -> int:
    data = generate_dataset(seed=args.seed, accounts=args.accounts)
    return _write_out(args, dataset_to_json(data),
                      f"generated synthetic stream: {args.accounts} "
                      f"accounts x {data['days']} days (seed={args.seed}) "
                      f"-> {args.out}")


def cmd_rules(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    holdout = slice_txns(data, *HOLDOUT_DAYS)
    scored = score_all(holdout, DEFAULT_PARAMS)
    payload = {"params": DEFAULT_PARAMS, "holdout_days": list(HOLDOUT_DAYS),
               "scores": scored["scores"],
               "total_alerts": scored["total_alerts"],
               "missed_cases": scored["missed_cases"]}
    return _write_out(args, canonical(payload) + "\n",
                      f"rules -> {args.out}")


def cmd_tune(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    result = tune_and_score(data)
    retro = retrospective(data, result["tuned_params"])
    payload = dict(result)
    payload["retrospective"] = retro
    return _write_out(args, canonical(payload) + "\n",
                      f"tune -> {args.out}")


def cmd_report(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    return _write_out(args, build_markdown_report(data),
                      f"report -> {args.out}")


def cmd_check(args) -> int:
    data = _load_or_error(args.input)
    if data is None:
        return EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    result = tune_and_score(data)
    retro = retrospective(data, result["tuned_params"])
    tuned = result["tuned_params"]
    print(f"accounts={data['account_count']} "
          f"transactions={len(data['transactions'])} "
          f"tuned_amount={tuned['amount_threshold']} "
          f"tuned_velocity={tuned['velocity_count']}/{tuned['velocity_sum']} "
          f"tuned_structuring={tuned['structuring_count']}")
    breaches = []
    for rule in REAL_RULES:
        s = result["holdout_tuned"]["scores"][rule]
        print(f"  {rule}: precision={s['precision']} recall={s['recall']} "
              f"alerts={s['alerts']}")
        if s["recall"] < MIN_HOLDOUT_RECALL:
            breaches.append(f"{rule} holdout recall {s['recall']} "
                            f"< {MIN_HOLDOUT_RECALL}")
    noise = retro["verdicts"]["round_amount"]["verdict"]
    print(f"  round_amount verdict={noise} "
          f"alerts_per_analyst_day={retro['alerts_per_analyst_day']}")
    if noise != "retire":
        breaches.append(f"round_amount verdict is {noise}, expected retire")
    if breaches:
        for b in breaches:
            print(f"check FAIL: {b}")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    def __init__(self):
        self.data: Dict = generate_dataset()


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(data: Optional[Dict] = None) -> None:
    _STATE.data = data if data is not None else generate_dataset()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, (canonical(payload) + "\n").encode(),
                   "application/json")

    def _dataset_from(self, body: Dict) -> Optional[Dict]:
        if "dataset" not in body:
            return _STATE.data
        candidate = body["dataset"]
        issues = validate_dataset(candidate)
        if issues:
            return None
        _STATE.data = candidate
        return candidate

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if self.path == "/report":
            return self._send(200, build_markdown_report(
                _STATE.data).encode(), "text/markdown; charset=utf-8")
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/tune", "/report"):
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw.strip() else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            data = self._dataset_from(body)
            if data is None:
                return self._send_json(400, {"error": "data quality"})
            if self.path == "/tune":
                result = tune_and_score(data)
                result["retrospective"] = retrospective(
                    data, result["tuned_params"])
                return self._send_json(200, result)
            return self._send_json(
                200, {"report": build_markdown_report(data)})
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    if args.input:
        data = _load_or_error(args.input)
        if data is None:
            return EXIT_ERROR
        reset_state(data)
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /tune, POST /report, GET /report, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transaction-monitoring-rule-tuning-kit",
        description="Transaction-monitoring rule tuning: thresholds "
                    "tuned on days 1-60, scored on held-out days 61-90.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate the synthetic stream")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--accounts", type=int, default=2000)
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_generate)

    for name, func, helptext in [
            ("rules", cmd_rules, "default-rule scores on the holdout"),
            ("tune", cmd_tune, "tune on days 1-60, score on 61-90"),
            ("report", cmd_report, "markdown tuning retrospective")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--input", required=True)
        s.add_argument("--out", default=None)
        s.set_defaults(func=func)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 breach / 2 error")
    c.add_argument("--input", required=True)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON/markdown API")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--input", default=None)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
