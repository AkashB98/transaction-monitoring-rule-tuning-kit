"""Shared builders for the test suite (not a test module).

Hand-built tiny streams where rule behaviour, scoring, and tuning
outcomes can be verified by hand.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def txn(tid, account, day, amount, kind="payment", planted=None):
    return {"txn_id": tid, "account_id": account, "day": day,
            "amount": float(amount), "kind": kind, "planted": planted}


def make_dataset(rows_by_account, days=90):
    """rows_by_account: {account_id: (archetype, [txn rows])}."""
    accounts, txns = [], []
    patterns = {"bad_amount": "amount", "bad_velocity": "velocity",
                "bad_structuring": "structuring"}
    for account_id, (archetype, rows) in sorted(rows_by_account.items()):
        pattern = patterns.get(archetype)
        accounts.append({"account_id": account_id, "archetype": archetype,
                         "is_bad": pattern is not None, "pattern": pattern})
        txns.extend(rows)
    return {"seed": 0, "days": days, "account_count": len(accounts),
            "accounts": accounts, "transactions": txns}
