"""Data-quality gate for the synthetic transaction stream.

Reports issues, never raises on bad data, so the CLI ``check`` gate
maps data problems to exit code 2, distinctly from a tuning-quality
breach (exit 1).
"""

from __future__ import annotations

from typing import Dict, List

from generator import ACCOUNT_FIELDS, ARCHETYPES, TXN_FIELDS

KINDS = ["deposit", "withdrawal", "payment"]
PLANTED = [None, "amount", "velocity", "structuring"]


def validate_dataset(dataset: Dict) -> List[str]:
    issues: List[str] = []
    if not isinstance(dataset, dict):
        return ["dataset must be a JSON object"]
    days = dataset.get("days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        return [f"dataset.days missing or invalid: {days!r}"]
    accounts = dataset.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        return ["dataset.accounts missing or empty"]
    txns = dataset.get("transactions")
    if not isinstance(txns, list) or not txns:
        return ["dataset.transactions missing or empty"]
    known = set()
    for row in accounts:
        if not isinstance(row, dict):
            issues.append("account row is not an object")
            continue
        for field in ACCOUNT_FIELDS:
            if field not in row:
                issues.append(f"missing field {field} in account {row!r:.60}")
        if row.get("archetype") not in ARCHETYPES:
            issues.append(f"bad archetype: {row.get('archetype')!r}")
        if not isinstance(row.get("is_bad"), bool):
            issues.append(f"is_bad must be bool for {row.get('account_id')}")
        known.add(row.get("account_id"))
    seen = set()
    for row in txns:
        if not isinstance(row, dict):
            issues.append("transaction row is not an object")
            continue
        for field in TXN_FIELDS:
            if field not in row:
                issues.append(f"missing field {field} in txn {row!r:.60}")
        tid = row.get("txn_id")
        if tid in seen:
            issues.append(f"duplicate txn_id: {tid}")
        seen.add(tid)
        if row.get("account_id") not in known:
            issues.append(f"unknown account_id: {row.get('account_id')}")
        day = row.get("day")
        if not isinstance(day, int) or isinstance(day, bool) \
                or not (1 <= day <= days):
            issues.append(f"bad day for {tid}: {day!r}")
        amt = row.get("amount")
        if not isinstance(amt, (int, float)) or isinstance(amt, bool) \
                or amt <= 0:
            issues.append(f"bad amount for {tid}: {amt!r}")
        if row.get("kind") not in KINDS:
            issues.append(f"bad kind for {tid}: {row.get('kind')!r}")
        if row.get("planted") not in PLANTED:
            issues.append(f"bad planted tag for {tid}: {row.get('planted')!r}")
    return issues
