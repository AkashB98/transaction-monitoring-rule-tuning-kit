"""The tuning retrospective: one deterministic markdown page.

Copied from computed numbers only — thresholds tuned on days 1-60,
every grade from held-out days 61-90, the below-the-line sample, and
a keep / watch / retire verdict per rule.
"""

from __future__ import annotations

from typing import Dict

from rules import (ALL_RULES, ANALYST_MINUTES_PER_ALERT, DEFAULT_PARAMS,
                   HOLDOUT_DAYS, MISSED_CASE_PENALTY_MINUTES, TUNE_DAYS,
                   below_the_line, slice_txns)
from tuning import retrospective, tune_and_score


def _rule_table(scores: Dict) -> str:
    lines = ["| Rule | Alerts | Precision | Recall | Missed | Cost (min) |",
             "|---|---|---|---|---|---|"]
    for rule in ALL_RULES:
        s = scores[rule]
        lines.append(f"| {rule} | {s['alerts']} | {s['precision']} | "
                     f"{s['recall']} | {s['missed_accounts']} | "
                     f"{s['cost_minutes']} |")
    return "\n".join(lines)


def build_markdown_report(dataset: Dict) -> str:
    ts = tune_and_score(dataset)
    tuned = ts["tuned_params"]
    retro = retrospective(dataset, tuned)
    holdout_txns = slice_txns(dataset, *HOLDOUT_DAYS)
    btl = below_the_line(holdout_txns, tuned)
    total_txns = len(dataset["transactions"])
    bad_accounts = sum(1 for a in dataset["accounts"] if a["is_bad"])

    lines = [
        "# Transaction monitoring — rule tuning retrospective",
        "",
        f"Synthetic stream: {dataset['account_count']} fictional accounts, "
        f"{total_txns} transactions over {dataset['days']} days "
        f"(seed {dataset['seed']}); {bad_accounts} planted bad-actor "
        "accounts across the amount / velocity / structuring patterns.",
        "",
        "Synthetic data only — NOT compliance-grade. Built to learn the "
        "problem shape named in a Solutions Architect JD.",
        "",
        f"## Tuning (days {TUNE_DAYS[0]}-{TUNE_DAYS[1]} only)",
        "",
        f"Cost objective: {ANALYST_MINUTES_PER_ALERT} analyst minutes per "
        f"alert x alert volume + {MISSED_CASE_PENALTY_MINUTES} minutes per "
        "missed planted case, minimised per rule over an explicit grid. "
        "Thresholds are tuned on days 1-60 and scored ONLY on held-out "
        "days 61-90 — never tuned and scored on the same data.",
        "",
        f"- amount_threshold: {DEFAULT_PARAMS['amount_threshold']} -> "
        f"**{tuned['amount_threshold']}**",
        f"- velocity: count {DEFAULT_PARAMS['velocity_count']} / sum "
        f"{DEFAULT_PARAMS['velocity_sum']} -> **count "
        f"{tuned['velocity_count']} / sum {tuned['velocity_sum']}**",
        f"- structuring_count: {DEFAULT_PARAMS['structuring_count']} -> "
        f"**{tuned['structuring_count']}**",
        "",
        f"## Held-out scores (days {HOLDOUT_DAYS[0]}-{HOLDOUT_DAYS[1]}, "
        "tuned thresholds)",
        "",
        _rule_table(ts["holdout_tuned"]["scores"]),
        "",
        f"Alert volume: {ts['holdout_tuned']['total_alerts']} alerts in "
        f"30 days = **{retro['alerts_per_analyst_day']} alerts per "
        f"analyst-day** ({retro['real_alerts_per_analyst_day']} from the "
        "three real rules). Of "
        f"{ts['holdout_tuned']['bad_accounts']} planted bad accounts "
        f"active in the holdout, the real rules caught "
        f"{ts['holdout_tuned']['caught_accounts']} and missed "
        f"{ts['holdout_tuned']['missed_cases']}.",
        "",
        "## Below the line (held-out, tuned thresholds)",
        "",
        "Transactions just under each line, sampled systematically "
        "(every 5th) to estimate what the rules miss:",
        "",
        f"- amount: band [{round(0.85 * tuned['amount_threshold'], 2)}, "
        f"{tuned['amount_threshold']}) holds {btl['amount']['band_size']} "
        f"transactions; {btl['amount']['planted_in_band']} are planted "
        "bad-amount transactions sitting just under the line.",
        f"- velocity: {btl['velocity']['near_miss_account_days']} "
        "account-days land within 3 transactions of the count line; "
        f"{btl['velocity']['planted_in_band']} planted velocity "
        "transactions sit in them.",
        f"- structuring: {btl['structuring']['band_deposits']} deposits "
        "sit in the just-under-reporting band; "
        f"{btl['structuring']['planted_in_band']} are planted "
        "structuring deposits (a deposit in the band is not itself a "
        "case — the rule needs the repetition).",
        "",
        "## Retrospective verdicts",
        "",
    ]
    for rule in ALL_RULES:
        v = retro["verdicts"][rule]
        lines.append(f"- **{rule}: {v['verdict'].upper()}** — {v['reason']}.")
    lines += [
        "",
        "The round_amount legacy rule is the retrospective's clear "
        "finding: it consumes the large majority of triage minutes and "
        "almost never lands on a planted case. Retire it; the three "
        "real rules carry the detection on their own.",
        "",
    ]
    return "\n".join(lines)
