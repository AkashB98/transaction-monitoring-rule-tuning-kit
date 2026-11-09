"""Deterministic synthetic transaction stream — fictional accounts.

SYNTHETIC DATA ONLY. No real person, account, or transaction data is
ever used. Every row is fabricated from a seeded PRNG so the same seed
always yields the same stream, byte-for-byte.

~2,000 accounts over 90 days. Roughly 4% of accounts are planted bad
actors, spread across three patterns a transaction-monitoring team
actually tunes rules for:

  * bad_amount      — single transactions far above normal size;
  * bad_velocity    — bursts of many transactions in one day;
  * bad_structuring — repeated deposits just under the $10,000
                      reporting threshold.

Legitimate look-alikes are planted on purpose, so no rule can score a
trivial precision of 1.0:

  * legit_payroll — payday bill bursts (many small transactions in a
                    day) that resemble velocity;
  * legit_salary  — one large monthly deposit ($9,100-$9,900) that
                    sits just under the reporting threshold and just
                    under a naive amount threshold, but never repeats
                    inside a week (so it is NOT structuring);
  * legit_mover   — a short burst of large deposits inside one week
                    (consolidating funds, e.g. before a purchase) that
                    genuinely trips the structuring rule;
  * plain legit accounts occasionally make one large purchase
                    ($9,500-$13,000) overlapping the low end of the
                    planted bad-amount range.

Every planted bad-pattern transaction carries a ground-truth tag in
its ``planted`` field (``amount`` / ``velocity`` / ``structuring``);
legitimate transactions — including every look-alike — carry ``None``.
The tags exist only because the data is synthetic: they are the labels
the rules are graded against, the way a tuning exercise grades alerts
against confirmed cases.
"""

from __future__ import annotations

import json
import random
from typing import Dict, List

DEFAULT_SEED = 42
DEFAULT_ACCOUNTS = 2000
DEFAULT_DAYS = 90

REPORTING_THRESHOLD = 10000.0

TXN_FIELDS = ["txn_id", "account_id", "day", "amount", "kind", "planted"]
ACCOUNT_FIELDS = ["account_id", "archetype", "is_bad", "pattern"]

ARCHETYPES = ["legit", "legit_payroll", "legit_rent", "legit_salary",
              "legit_mover", "bad_amount", "bad_velocity",
              "bad_structuring"]
BAD_PATTERNS = ["amount", "velocity", "structuring"]

# (archetype, share of accounts) — shares sum to 1.0; the bad three
# total 0.040 (4.0% planted bad actors at the default size).
_SHARES = [("bad_amount", 0.0135), ("bad_velocity", 0.0135),
           ("bad_structuring", 0.013), ("legit_payroll", 0.04),
           ("legit_rent", 0.04), ("legit_salary", 0.03),
           ("legit_mover", 0.02), ("legit", 0.83)]


def archetype_counts(accounts: int) -> Dict[str, int]:
    """Split ``accounts`` across archetypes (pure function of count)."""
    counts: Dict[str, int] = {}
    used = 0
    for name, share in _SHARES:
        if name == "legit":
            continue
        counts[name] = int(round(accounts * share))
        used += counts[name]
    counts["legit"] = accounts - used
    return counts


def _archetype_plan(accounts: int) -> List[str]:
    counts = archetype_counts(accounts)
    plan: List[str] = []
    for name, _share in _SHARES:
        plan.extend([name] * counts[name])
    return plan


def _pattern_of(archetype: str):
    return {"bad_amount": "amount", "bad_velocity": "velocity",
            "bad_structuring": "structuring"}.get(archetype)


def _small_amount(rng: random.Random) -> float:
    """An ordinary transaction amount; ~22% are exact round hundreds
    (the noise rule's favourite shape)."""
    if rng.random() < 0.22:
        return float(rng.choice([20, 40, 50, 60, 80, 100, 120, 150, 200,
                                 250, 300, 400, 500, 600, 800, 1000]))
    return round(rng.uniform(5.0, 2400.0), 2)


def _background(rng: random.Random, add, account_id: str, day: int) -> None:
    """Ordinary activity for one account on one day (maybe none)."""
    if rng.random() < 0.16:
        for _ in range(rng.choice([1, 1, 1, 2])):
            add(account_id, day, _small_amount(rng),
                rng.choice(["payment", "payment", "deposit", "withdrawal"]),
                None)


def generate_dataset(accounts: int = DEFAULT_ACCOUNTS,
                     seed: int = DEFAULT_SEED,
                     days: int = DEFAULT_DAYS) -> Dict:
    """Return the synthetic stream, deterministic for ``seed``."""
    if accounts < 0:
        raise ValueError("accounts must be >= 0")
    if days < 1:
        raise ValueError("days must be >= 1")
    rng = random.Random(seed)
    plan = _archetype_plan(accounts)
    account_rows: List[Dict] = []
    txns: List[Dict] = []
    seq = [0]  # mutable counter for txn ids, in generation order

    def add(account_id: str, day: int, amount: float, kind: str,
            planted) -> None:
        seq[0] += 1
        txns.append({"txn_id": f"T{seq[0]:06d}", "account_id": account_id,
                     "day": day, "amount": round(float(amount), 2),
                     "kind": kind, "planted": planted})

    for idx, archetype in enumerate(plan):
        account_id = f"A{idx + 1:04d}"
        pattern = _pattern_of(archetype)
        account_rows.append({"account_id": account_id,
                             "archetype": archetype,
                             "is_bad": pattern is not None,
                             "pattern": pattern})
        # Pre-plan this account's special events (RNG draws happen in a
        # fixed per-account order, so the stream is deterministic).
        if archetype == "bad_amount":
            event_days = sorted(rng.sample(range(1, days + 1), 4))
            amounts = [round(rng.uniform(10500.0, 16000.0), 2)
                       for _ in event_days]
            special = {d: a for d, a in zip(event_days, amounts)}
        elif archetype == "bad_velocity":
            burst_days = sorted(rng.sample(range(1, days + 1), 10))
            special = {d: rng.randint(11, 16) for d in burst_days}
        elif archetype == "bad_structuring":
            episodes = []
            for start in sorted(rng.sample(range(1, days - 8), 4)):
                n = rng.randint(3, 5)
                episodes.append((start, n))
            special = {}
            for start, n in episodes:
                for k in range(n):
                    special[start + k] = round(rng.uniform(8200.0, 9900.0), 2)
        elif archetype == "legit_payroll":
            special = {d: rng.randint(8, 12)
                       for d in range(1, days + 1) if d % 15 == 1}
        elif archetype == "legit_salary":
            special = {d: round(rng.uniform(9100.0, 9900.0), 2)
                       for d in (15, 45, 75) if d <= days}
        elif archetype == "legit_rent":
            special = {d: round(rng.uniform(1950.0, 1990.0), 2)
                       for d in (5, 35, 65) if d <= days}
        elif archetype == "legit_mover":
            special = {}
            for start in (20, 70):
                if start + 2 <= days:
                    for k in range(3):
                        special[start + k] = round(
                            rng.uniform(8000.0, 9500.0), 2)
        elif archetype == "legit":
            special = {}
            if rng.random() < 0.02:
                d = rng.randint(1, days)
                special = {d: round(rng.uniform(9500.0, 13000.0), 2)}
        else:  # pragma: no cover - plan only emits known archetypes
            special = {}

        for day in range(1, days + 1):
            if archetype == "bad_amount" and day in special:
                add(account_id, day, special[day], "payment", "amount")
            elif archetype == "bad_velocity" and day in special:
                for _ in range(special[day]):
                    add(account_id, day,
                        round(rng.uniform(700.0, 1400.0), 2),
                        "payment", "velocity")
            elif archetype == "bad_structuring" and day in special:
                add(account_id, day, special[day], "deposit",
                    "structuring")
            elif archetype == "legit_payroll" and day in special:
                for _ in range(special[day]):
                    add(account_id, day,
                        round(rng.uniform(40.0, 700.0), 2),
                        "payment", None)
            elif archetype == "legit_salary" and day in special:
                add(account_id, day, special[day], "deposit", None)
            elif archetype == "legit_rent" and day in special:
                add(account_id, day, special[day], "payment", None)
            elif archetype == "legit_mover" and day in special:
                add(account_id, day, special[day], "deposit", None)
            elif archetype == "legit" and day in special:
                add(account_id, day, special[day], "payment", None)
            _background(rng, add, account_id, day)

    return {"seed": seed, "days": days, "account_count": accounts,
            "accounts": account_rows, "transactions": txns}


def dataset_to_json(dataset: Dict) -> str:
    return json.dumps(dataset, sort_keys=True) + "\n"
