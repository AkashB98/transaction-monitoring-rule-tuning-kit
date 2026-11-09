"""Threshold tuning on days 1-60 ONLY, scored on held-out days 61-90.

The split is the whole point of the exercise: a threshold tuned and
scored on the same transactions grades its own homework. ``tune``
filters the stream to the tuning window and asserts nothing outside
it leaked in; holdout scoring asserts the mirror image. The guard is
executable, not a comment — a test feeds overlapping windows and
expects the assertion to fire.

Each real rule is tuned independently over a small explicit grid,
minimising that rule's **cost objective** — analyst minutes per
alert x alert volume + penalty per missed planted case. Ties break
toward the earlier grid entry (grids are ordered most-permissive
first, so a tie keeps the rule that catches more).
"""

from __future__ import annotations

from typing import Dict, List

from rules import (DEFAULT_PARAMS, HOLDOUT_DAYS, REAL_RULES, TUNE_DAYS,
                   evaluate_alerts, rule_cost, score_all, score_rule,
                   slice_txns)

AMOUNT_GRID = [9000.0, 10000.0, 11000.0, 12000.0, 13000.0]
VELOCITY_COUNT_GRID = [8, 10, 11, 12, 13, 14]
VELOCITY_SUM_GRID = [10000.0, 15000.0, 20000.0, 30000.0]
STRUCTURING_GRID = [2, 3, 4, 5]

# The planted band the tuned amount threshold is expected to land in:
# planted bad-amount transactions run $10,500-$16,000 and legitimate
# large transactions overlap them at $9,500-$13,000, so any threshold
# that balances alert cost against missed cases lands in here.
AMOUNT_BAND = (10000.0, 14000.0)


def assert_window_isolation(tune_txns: List[Dict],
                            score_txns: List[Dict]) -> None:
    """Raise AssertionError if tuning and scoring windows overlap."""
    tune_days = {t["day"] for t in tune_txns}
    score_days = {t["day"] for t in score_txns}
    overlap = tune_days & score_days
    assert not overlap, (
        f"tuning/scoring leakage: days {sorted(overlap)[:5]} appear in "
        "both windows — never tune and score on the same data")


def _tune_one(txns: List[Dict], rule: str, candidates: List[Dict]) -> Dict:
    best = None
    for cand in candidates:
        params = dict(DEFAULT_PARAMS)
        params.update(cand)
        alerts = evaluate_alerts(txns, params, include_noise=False)
        score = score_rule(txns, alerts, rule)
        cost = rule_cost(score)
        entry = {"params": cand, "cost_minutes": cost,
                 "precision": score["precision"],
                 "recall": score["recall"], "alerts": score["alerts"],
                 "missed_accounts": score["missed_accounts"]}
        if best is None or cost < best["cost_minutes"]:
            best = entry
    assert best is not None
    return best


def tune(dataset: Dict) -> Dict:
    """Tune on days 1-60 only; return tuned params + tuning detail."""
    tune_txns = slice_txns(dataset, *TUNE_DAYS)
    holdout_txns = slice_txns(dataset, *HOLDOUT_DAYS)
    assert tune_txns, "tuning window is empty"
    assert all(TUNE_DAYS[0] <= t["day"] <= TUNE_DAYS[1]
               for t in tune_txns), "non-tuning day leaked into tuning"
    assert_window_isolation(tune_txns, holdout_txns)

    amount = _tune_one(tune_txns, "amount",
                       [{"amount_threshold": v} for v in AMOUNT_GRID])
    velocity = _tune_one(
        tune_txns, "velocity",
        [{"velocity_count": c, "velocity_sum": s}
         for c in VELOCITY_COUNT_GRID for s in VELOCITY_SUM_GRID])
    structuring = _tune_one(
        tune_txns, "structuring",
        [{"structuring_count": k} for k in STRUCTURING_GRID])

    tuned = dict(DEFAULT_PARAMS)
    tuned.update(amount["params"])
    tuned.update(velocity["params"])
    tuned.update(structuring["params"])
    detail = {"amount": amount, "velocity": velocity,
              "structuring": structuring}
    return {"params": tuned, "tune_days": list(TUNE_DAYS),
            "detail": detail}


def tune_and_score(dataset: Dict) -> Dict:
    """Full exercise: tune on 1-60, score defaults + tuned on 61-90."""
    tuned = tune(dataset)
    holdout_txns = slice_txns(dataset, *HOLDOUT_DAYS)
    assert all(HOLDOUT_DAYS[0] <= t["day"] <= HOLDOUT_DAYS[1]
               for t in holdout_txns), "non-holdout day in holdout score"
    tune_txns = slice_txns(dataset, *TUNE_DAYS)
    return {
        "tuned_params": tuned["params"],
        "tune_days": list(TUNE_DAYS), "holdout_days": list(HOLDOUT_DAYS),
        "tuning_detail": tuned["detail"],
        "tune_scores": _strip(score_all(tune_txns, tuned["params"])),
        "holdout_default": _strip(score_all(holdout_txns, DEFAULT_PARAMS)),
        "holdout_tuned": _strip(score_all(holdout_txns, tuned["params"])),
    }


def _strip(scored: Dict) -> Dict:
    out = dict(scored)
    out.pop("alerts", None)
    return out


def retrospective(dataset: Dict, params: Dict) -> Dict:
    """Grade every rule on the held-out window and say which earn
    their keep. A rule is retired when its holdout precision is under
    0.10 (its alerts are almost never a real case) while it still
    generates volume; kept when it catches at least half its planted
    pattern at precision 0.25 or better; otherwise watch."""
    holdout_txns = slice_txns(dataset, *HOLDOUT_DAYS)
    scored = score_all(holdout_txns, params)
    days = HOLDOUT_DAYS[1] - HOLDOUT_DAYS[0] + 1
    verdicts = {}
    for rule, s in scored["scores"].items():
        per_day = round(s["alerts"] / days, 2)
        if s["precision"] < 0.10 and s["alerts"] > 0:
            verdict = "retire"
            reason = (f"precision {s['precision']} — alerts are almost "
                      "never a planted case, at "
                      f"{per_day} alerts/analyst-day of pure triage")
        elif s["precision"] >= 0.25 and s["recall"] >= 0.5:
            verdict = "keep"
            reason = (f"precision {s['precision']}, recall {s['recall']} "
                      f"at {per_day} alerts/analyst-day")
        else:
            verdict = "watch"
            reason = (f"precision {s['precision']}, recall {s['recall']} "
                      f"at {per_day} alerts/analyst-day")
        verdicts[rule] = {"verdict": verdict, "reason": reason,
                          "alerts_per_analyst_day": per_day,
                          "precision": s["precision"],
                          "recall": s["recall"], "alerts": s["alerts"],
                          "cost_minutes": s["cost_minutes"]}
    total_alerts = scored["total_alerts"]
    return {"verdicts": verdicts, "holdout_days": list(HOLDOUT_DAYS),
            "total_holdout_alerts": total_alerts,
            "alerts_per_analyst_day": round(total_alerts / days, 2),
            "real_alerts_per_analyst_day":
                round(scored["real_alerts"] / days, 2),
            "missed_cases": scored["missed_cases"],
            "caught_accounts": scored["caught_accounts"],
            "bad_accounts": scored["bad_accounts"]}
