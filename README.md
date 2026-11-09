# transaction-monitoring-rule-tuning-kit

**The Alloy Senior Solutions Architect, Transaction Monitoring JD (surfaced 2026-11-03) named the gap directly: solutions engineers who can stand in front of a financial institution's monitoring stack and talk about how rules get tuned, what an alert queue costs, and why a rule should be retired. This repo is that conversation, made runnable: three monitoring rules tuned on 60 days of synthetic transactions, graded honestly on 30 held-out days, with a cost objective, a below-the-line sample, and a retrospective that retires the rule that does not earn its keep.**

> **Honesty line: this project is synthetic and NOT compliance-grade. Built to learn the problem shape named in a Solutions Architect JD — it does not represent AML, fraud-operations, or transaction-monitoring employment experience, and no real transaction data is used anywhere in it.**

A **transaction monitoring** system watches account activity and raises **alerts** — flagged account-days a human analyst must review — when activity matches a rule. The tuning problem is a trade: thresholds set low drown analysts in false alerts; set high, real cases slip through. This kit builds the whole loop on a seeded synthetic stream: plant known bad-actor patterns, fire explicit rules, **tune** — search for the thresholds with the best cost outcome — on days 1–60 only, **score** — grade the tuned rules on data they never saw — on held-out days 61–90, sample **below the line** — inspect transactions just under each threshold to estimate what the rules miss — and write the retrospective a monitoring team actually writes: which rules earn their keep, and which one gets retired.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies.

## Same discipline, different domain

Two sibling projects run the identical discipline — deterministic synthetic data, an explicit train/grading split, pinned golden evals — on different problems:

- **shadow-mode-policy-simulator** — a candidate policy runs in shadow mode against a live one and is graded on the cases where they disagree, before it is allowed to act. Same discipline (never grade a change on the data that shaped it), different domain (agent policy).
- **credit-retrospective-kit** — closed credit vintages are graded backwards: did the score work, and where did it drift? Same discipline (planted ground truth, honest held-out numbers), different domain (credit underwriting).

## Quickstart

```bash
# 1. Generate the synthetic stream (2,000 accounts x 90 days, seed 42)
python3 cli.py generate --out stream.json

# 2. Default-rule scores on the held-out window (days 61-90)
python3 cli.py rules --input stream.json

# 3. Tune on days 1-60, score on days 61-90, with the retrospective
python3 cli.py tune --input stream.json

# 4. The tuning retrospective (markdown, not a dashboard)
python3 cli.py report --input stream.json

# 5. CI gate: exit 0 = pass, 1 = quality breach (a real rule below
#    its holdout recall floor, or the noise rule not retired),
#    2 = data-quality / IO error. Seeded data exits 0.
python3 cli.py check --input stream.json

# 6. One-command end-to-end demo (incl. a live serve round-trip)
python3 demo.py

# 7. Tiny localhost API: POST /tune, POST /report, GET /report, GET /health
python3 cli.py serve --port 8765
```

## The seeded stream at a glance (seed 42)

**2,000 fictional accounts, 45,556 transactions over 90 days, 80 planted bad-actor accounts (4.0%)** spread across the three patterns. Seven **archetypes** — behavioural patterns given to groups of accounts so the signals are real, not noise:

| Archetype | Accounts | Planted behaviour |
|---|---|---|
| bad_amount | 27 | 4 single transactions of $10,500–$16,000 |
| bad_velocity | 27 | 10 burst days of 11–16 transactions |
| bad_structuring | 26 | 4 episodes of 3–5 deposits of $8,200–$9,900 inside a week |
| legit_payroll | 80 | payday bursts of 8–12 small payments every 15 days — the velocity look-alike |
| legit_salary | 60 | one deposit of $9,100–$9,900 a month — just under the line, never repeated in a week |
| legit_mover | 40 | 3 deposits of $8,000–$9,500 inside one week, twice — genuinely trips structuring |
| legit_rent | 80 | rent of $1,950–$1,990 a month — just under a round number |
| legit | 1,660 | ordinary activity; ~2% make one purchase of $9,500–$13,000, overlapping the bad-amount range |

The look-alikes are the point: a rule tuned against clean data scores a flattering, useless 1.0. Here precision has to be earned.

## The rules

Three real rules, each an explicit threshold set an analyst can argue with in a review meeting:

- **amount** — a single transaction at or above `amount_threshold` (one alert per account-day, carrying the largest amount).
- **velocity** — `velocity_count` transactions **or** `velocity_sum` dollars for one account in one day (a 24-hour window).
- **structuring** — `structuring_count` deposits inside a 7-day window, each in the band [$7,500, $10,000) just under the $10,000 reporting threshold.

Plus one legacy rule:

- **round_amount (noise)** — any transaction whose amount is an exact multiple of $100. Nobody re-validated it; ordinary activity is full of round amounts. It never counts toward catching a bad actor.

## Tuning: days 1–60 only, scored on days 61–90

**Never tune and score on the same data** — a threshold graded on its own tuning window grades its own homework. The split is enforced in code, not just documented: `tune()` filters to days 1–60 and asserts nothing outside leaked in; the isolation assertion fires on any overlapping windows and is pinned by a test and by eval E8.

Each rule is tuned independently over a small explicit grid, minimising its **cost objective** — the total analyst cost of running the rule, in minutes:

```
cost = 12 minutes per alert x alert volume + 480 minutes per missed planted case
```

| Parameter | Default | Tuned (days 1–60) |
|---|---|---|
| amount_threshold | $10,000 | **$11,000** |
| velocity_count / velocity_sum | 10 / $15,000 | **14 / $20,000** |
| structuring_count | 3 | **3** |

## Held-out results (days 61–90, tuned thresholds)

| Rule | Alerts | Precision | Recall | Verdict |
|---|---|---|---|---|
| amount | 49 | 0.6667 | 0.9524 | KEEP |
| velocity | 51 | 0.8846 | 0.8846 | KEEP |
| structuring | 80 | 0.3443 | 1.0 | KEEP |
| round_amount | 1,261 | 0.0322 | — | **RETIRE** |

- **Precision** — of the accounts a rule alerted on, the share that are really its planted pattern. **Recall** — of the planted accounts active in the window, the share the rule caught.
- Structuring's 40 false-positive accounts are *exactly* the 40 planted legit_mover accounts: real behaviour the rule cannot distinguish from structuring, priced honestly instead of tuned away.
- Amount's 10 false positives are planted legitimate large purchases ($9,500–$13,000) that overlap the bad range — no threshold separates them, and the tuned $11,000 is the cost-minimising compromise, inside the planted band the evals check for.
- The three real rules together catch **64 of 68** planted bad accounts active in the holdout and miss 4.
- Tuning cut held-out alert volume from 1,605 (defaults) to **1,441**, and lifted velocity precision from 0.243 (defaults — payday bursts everywhere) to 0.8846.

**Alert volume: 48.03 alerts per analyst-day in total — but 42.03 of them are the noise rule.** The three real rules together generate 6.0 alerts per analyst-day. That ratio *is* the retrospective: one legacy rule consumes 87% of triage time (15,132 of the cost minutes) at a precision of 0.0322.

## Below the line

**Below-the-line sampling** — inspecting the transactions a rule did *not* fire on, just under its threshold, to estimate what it misses. On the held-out window at tuned thresholds (systematic every-5th sample):

- **amount:** the band [$9,350, $11,000) holds 115 transactions; 3 are planted bad-amount transactions sitting just under the line.
- **velocity:** 110 account-days land within 3 transactions of the count line; 531 planted velocity transactions sit inside them (bursts of 11–13 that the tuned count of 14 lets through — the accepted price of silencing the payroll false alarms).
- **structuring:** 325 deposits sit in the just-under-reporting band; 145 are planted structuring deposits. A deposit in the band is not itself a case — the rule needs the repetition — which is exactly what the sample teaches.

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic stream: 2,000 fictional accounts, 90 days, three planted bad patterns + four legitimate look-alike archetypes; ground-truth tags on planted transactions |
| `validation.py` | Data-quality gate (fields, day range, kinds, tags, duplicates); reports issues, never raises on bad data |
| `rules.py` | The three real rules + the noise rule, account-level precision/recall scoring, the cost objective, below-the-line sampling |
| `tuning.py` | Grid tuning on days 1–60 with the isolation assertion, held-out scoring, and the keep/watch/retire retrospective |
| `report.py` | The markdown tuning retrospective, copied from the computed numbers |
| `cli.py` | `generate` / `rules` / `tune` / `report` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /tune`, `POST /report`, `GET /report`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: determinism, the split, verdicts, check exit codes, live localhost serve round-trip |
| `fixtures/` | A 200-account seeded stream (`sample_stream.json`, 4,599 transactions) with pinned totals |

## Evals

`python3 evals/run_evals.py` → **14/14 golden evals**, report committed at `evals/eval_report.json` (md5 `8fb01031fab9857e6594186f50450dd1`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 dataset bytes pinned by md5
- **E2** headline counts (45,556 transactions, 80 planted bad accounts = 4.0%)
- **E3** tuned thresholds pinned (11000 / 14 / 20000 / 3); amount inside the planted band
- **E4** holdout per-rule precision/recall pinned (amount 0.6667/0.9524, velocity 0.8846/0.8846, structuring 0.3443/1.0)
- **E5** the split matters: velocity is 1.0/1.0 on its tuning window and 0.8846 on the holdout — both sides pinned
- **E6** retrospective retires round_amount and keeps the three real rules
- **E7** alert volume pinned (48.03 per analyst-day total, 6.0 from the real rules, 1,261 noise alerts)
- **E8** tuning/scoring isolation asserted — overlapping windows raise
- **E9** below-the-line pinned (amount band 115 transactions / 3 planted; structuring band 325 deposits / 145 planted)
- **E10** tuned beats default volume on the holdout (1,441 vs 1,605 alerts; 64/68 cases caught)
- **E11** CLI `check` exit codes 0 / 2
- **E12** serve round-trip matches local tune + report exactly
- **E13** bundled fixture pinned (200 accounts, 4,599 transactions, validates clean)
- **E14** report determinism + the honesty line

Unit tests: `python3 -m unittest discover -s tests` → **68 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-scored rule cases (each rule's fire / no-fire edges, the salary pattern that must never trip structuring), window-isolation tests that expect the leakage assertion to fire, validation defects, CLI exit codes, and serve round-trips.

## Development loop — what the checks actually found

No fabricated war stories: these are the three findings the seeded numbers themselves produced, each now pinned so it cannot quietly drift.

1. **The tuning window flatters velocity; the holdout corrects it.** On days 1–60 the tuned velocity rule scores a perfect precision 1.0 / recall 1.0 — no payroll account crosses count 14 there. On days 61–90 three payroll accounts *do* cross it (a 12-payment payday plus 2 ordinary transactions the same day makes 14), and three burst accounts fall short, landing at 0.8846 / 0.8846. Eval E5 pins both sides of that gap: a portfolio that only reported the tuning number would be lying by omission.
2. **Structuring's precision ceiling is set by a look-alike, not by the threshold.** Every one of the 40 false-positive accounts at the tuned threshold is a planted legit_mover — the behaviour is genuinely indistinguishable at the transaction level. No threshold on *repetition count* separates a mover from a structurer; the retrospective keeps the rule (recall 1.0 at 2.67 alerts/day is a fair price) and says why, instead of pretending a better threshold exists.
3. **The noise rule's recall is the trap.** round_amount "catches" 30 of 68 bad accounts in the holdout — a number that, quoted alone, has kept rules like it alive in real queues. Its precision (0.0322) and its 42.03 alerts per analyst-day are the numbers that retire it, so the retrospective leads with cost and precision, and the verdict logic keys on them, never on recall alone.

## Scope and honest limits

- **NOT compliance-grade.** No sanctions screening, no case management, no SAR workflow, no model-risk documentation — the real discipline has all of these; this kit models only the rule-tuning loop named in the JD.
- **Planted labels are a teaching device.** Real tuning grades alerts against analyst dispositions and confirmed cases, which are noisier and slower than synthetic ground truth; precision/recall here are cleaner than any real queue's.
- **Account-level scoring.** A rule is graded on whether it alerted the right *account* in the window, not on alert-to-case deduplication, analyst SLA, or time-to-detect.
- **Day-granularity windows.** Velocity uses a calendar day as its 24-hour window and structuring a 7-day sliding window; real systems window on timestamps.
- **Independent per-rule tuning.** Rules are tuned one at a time against their own cost; joint tuning (rules interacting, e.g. amount alerts suppressing velocity alerts on the same account-day) is the obvious next step.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its stream in memory, and resets on restart.

## Why this project

The Solutions Architect gap the Alloy JD named is not "can you write a rule" — it is "can you sit with a monitoring team and reason about thresholds, alert cost, and retirement with numbers you can defend." This project practises exactly that reasoning end-to-end: plant the patterns, tune on one window, be graded on another, sample below the line, and retire what does not earn its keep — with every number reproducible from a seed and pinned by an eval.
