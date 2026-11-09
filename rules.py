"""The monitoring rules, alert scoring, the cost objective, and the
below-the-line sample.

Exactly three real rules plus one legacy noise rule:

  * ``amount``      — a single transaction at or above a threshold;
  * ``velocity``    — N transactions OR $X total for one account in
                      one day (a 24-hour window);
  * ``structuring`` — K deposits inside a 7-day window, each in the
                      band just under the $10,000 reporting threshold;
  * ``round_amount`` (noise) — any transaction whose amount is an
                      exact multiple of $100. A legacy rule nobody
                      re-validated: it fires constantly on ordinary
                      activity. It never counts toward catching a bad
                      actor, and the retrospective exists to retire it.

Alerts are account-day events: one alert per (rule, account, day),
carrying the evidence (largest amount / count / window count) that
fired it. An analyst reviews alerts, not raw transactions, so alert
volume — not transaction volume — is what the cost objective prices.

Scoring is account-level against the planted ground-truth tags: for a
rule and a day range, a true positive is a planted-pattern account
with at least one planted transaction of that pattern in the range
that the rule also alerted on in the range.

**cost objective** — total analyst cost of running a rule, in
minutes: ``minutes per alert x alert volume + penalty per missed
planted case``. Tuning minimises this on the tuning window only.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from generator import REPORTING_THRESHOLD

REAL_RULES = ["amount", "velocity", "structuring"]
ALL_RULES = REAL_RULES + ["round_amount"]
RULE_PATTERN = {"amount": "amount", "velocity": "velocity",
                "structuring": "structuring"}

ANALYST_MINUTES_PER_ALERT = 12
MISSED_CASE_PENALTY_MINUTES = 480

STRUCTURING_BAND_LOW = 7500.0
STRUCTURING_WINDOW_DAYS = 7

DEFAULT_PARAMS: Dict = {
    "amount_threshold": 10000.0,
    "velocity_count": 10,
    "velocity_sum": 15000.0,
    "structuring_count": 3,
}

TUNE_DAYS = (1, 60)
HOLDOUT_DAYS = (61, 90)


def slice_txns(dataset: Dict, day_lo: int, day_hi: int) -> List[Dict]:
    return [t for t in dataset["transactions"]
            if day_lo <= t["day"] <= day_hi]


def slice_dataset(dataset: Dict, day_lo: int, day_hi: int) -> Dict:
    out = dict(dataset)
    out["transactions"] = slice_txns(dataset, day_lo, day_hi)
    return out


def _alert(rule: str, account_id: str, day: int, **evidence) -> Dict:
    row = {"rule": rule, "account_id": account_id, "day": day}
    row.update(evidence)
    return row


def evaluate_alerts(txns: List[Dict], params: Dict,
                    include_noise: bool = True) -> List[Dict]:
    """Fire every rule over ``txns``; alerts sorted deterministically."""
    alerts: List[Dict] = []
    by_account_day: Dict = {}
    for t in txns:
        by_account_day.setdefault((t["account_id"], t["day"]), []).append(t)

    for (account_id, day), rows in sorted(by_account_day.items()):
        biggest = max(r["amount"] for r in rows)
        if biggest >= params["amount_threshold"]:
            alerts.append(_alert("amount", account_id, day,
                                 max_amount=biggest,
                                 txn_count=len(rows)))
        total = round(sum(r["amount"] for r in rows), 2)
        if len(rows) >= params["velocity_count"] \
                or total >= params["velocity_sum"]:
            alerts.append(_alert("velocity", account_id, day,
                                 txn_count=len(rows), total_amount=total))
        if include_noise and any(
                float(r["amount"]).is_integer()
                and int(r["amount"]) % 100 == 0 for r in rows):
            alerts.append(_alert("round_amount", account_id, day,
                                 txn_count=len(rows)))

    # Structuring: greedy episodes per account over band deposits.
    deposits: Dict[str, List[Dict]] = {}
    for t in txns:
        if t["kind"] == "deposit" \
                and STRUCTURING_BAND_LOW <= t["amount"] < REPORTING_THRESHOLD:
            deposits.setdefault(t["account_id"], []).append(t)
    for account_id, rows in sorted(deposits.items()):
        rows = sorted(rows, key=lambda r: (r["day"], r["txn_id"]))
        episode: List[Dict] = []
        for row in rows:
            episode = [e for e in episode
                       if row["day"] - e["day"] < STRUCTURING_WINDOW_DAYS]
            episode.append(row)
            if len(episode) >= params["structuring_count"]:
                alerts.append(_alert(
                    "structuring", account_id, row["day"],
                    window_count=len(episode),
                    window_start=episode[0]["day"],
                    total_amount=round(sum(e["amount"] for e in episode), 2)))
                episode = []
    alerts.sort(key=lambda a: (a["day"], a["account_id"], a["rule"]))
    return alerts


def _planted_accounts(txns: List[Dict], pattern: str) -> set:
    return {t["account_id"] for t in txns if t["planted"] == pattern}


def score_rule(txns: List[Dict], alerts: List[Dict], rule: str) -> Dict:
    """Account-level precision / recall for one rule over ``txns``."""
    rule_alerts = [a for a in alerts if a["rule"] == rule]
    alerted = {a["account_id"] for a in rule_alerts}
    if rule == "round_amount":
        truth = {t["account_id"] for t in txns if t["planted"] is not None}
    else:
        truth = _planted_accounts(txns, RULE_PATTERN[rule])
    tp = len(alerted & truth)
    fp = len(alerted - truth)
    fn = len(truth - alerted)
    precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) else 0.0
    return {"rule": rule, "alerts": len(rule_alerts),
            "alerted_accounts": len(alerted),
            "true_positive_accounts": tp, "false_positive_accounts": fp,
            "missed_accounts": fn, "planted_accounts": len(truth),
            "precision": precision, "recall": recall}


def rule_cost(score: Dict) -> int:
    """Cost objective for one scored rule, in analyst minutes."""
    return (ANALYST_MINUTES_PER_ALERT * score["alerts"]
            + MISSED_CASE_PENALTY_MINUTES * score["missed_accounts"])


def score_all(txns: List[Dict], params: Dict,
              include_noise: bool = True) -> Dict:
    alerts = evaluate_alerts(txns, params, include_noise=include_noise)
    scores = {}
    for rule in (ALL_RULES if include_noise else REAL_RULES):
        s = score_rule(txns, alerts, rule)
        s["cost_minutes"] = rule_cost(s) if rule != "round_amount" else \
            ANALYST_MINUTES_PER_ALERT * s["alerts"]
        scores[rule] = s
    real_alerts = [a for a in alerts if a["rule"] in REAL_RULES]
    caught = {a["account_id"] for a in real_alerts}
    bad = {t["account_id"] for t in txns if t["planted"] is not None}
    return {"scores": scores, "alerts": alerts,
            "total_alerts": len(alerts),
            "real_alerts": len(real_alerts),
            "bad_accounts": len(bad),
            "caught_accounts": len(bad & caught),
            "missed_cases": len(bad - caught)}


def below_the_line(txns: List[Dict], params: Dict) -> Dict:
    """**below-the-line sampling** — inspecting transactions just
    under a threshold to estimate what the rule misses (the sample a
    tuning team pulls precisely because the rule never fired on it).

    Deterministic systematic sample: every 5th transaction in each
    just-under band, in stream order. Reports the sampled bad share
    and the extrapolated estimate of planted transactions sitting
    just under the line.
    """
    out: Dict = {}
    amt_lo = round(0.85 * params["amount_threshold"], 2)
    amt_band = [t for t in txns
                if amt_lo <= t["amount"] < params["amount_threshold"]]
    out["amount"] = _band_stats(amt_band, "amount")
    vel_lo = params["velocity_count"] - 3
    by_day: Dict = {}
    for t in txns:
        by_day.setdefault((t["account_id"], t["day"]), []).append(t)
    # Near-miss account-days (count just under the line), flattened to
    # their transactions for sampling.
    near_days = [rows for (_k, rows) in sorted(by_day.items())
                 if vel_lo <= len(rows) < params["velocity_count"]]
    flat = [t for rows in near_days for t in rows]
    out["velocity"] = _band_stats(flat, "velocity")
    out["velocity"]["near_miss_account_days"] = len(near_days)
    band_deps = [t for t in txns if t["kind"] == "deposit"
                 and STRUCTURING_BAND_LOW <= t["amount"]
                 < REPORTING_THRESHOLD]
    out["structuring"] = _band_stats(band_deps, "structuring")
    out["structuring"]["band_deposits"] = len(band_deps)
    return out


def _band_stats(band: List[Dict], pattern: str) -> Dict:
    sample = band[::5]
    planted_total = sum(1 for t in band if t["planted"] == pattern)
    planted_sampled = sum(1 for t in sample if t["planted"] == pattern)
    share = round(planted_sampled / len(sample), 4) if sample else 0.0
    return {"band_size": len(band), "sampled": len(sample),
            "planted_in_band": planted_total,
            "planted_in_sample": planted_sampled,
            "planted_share_of_sample": share,
            "estimated_planted_just_under_line": planted_total}
