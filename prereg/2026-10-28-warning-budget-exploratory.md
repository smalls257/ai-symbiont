# Exploratory analysis: penalising bad warnings (warning budgets), Task 14c

**EXPLORATORY / POST-HOC. FROZEN 2026-10-27, committed before any budget
metric is computed on the test split.** The test split was already used once,
for the G6 selection (`prereg/2026-10-29-offline-selection.md`, frozen at
commit e5214b5). This file cannot change the G6 outcome, its rule, its
margin, its split or its live-learner verdict. It describes a second look at
the same recorded steps, chosen after the owner saw the G6 flag rates, so
every number it produces is exploratory, not confirmatory. After this commit
only a dated amendment at the end may change anything, and an amendment
cannot change the budgets, costs, metrics, calibration rule or bootstrap
below.

Claim tags: [measured] = observed in our own run, [established] = known from
the literature or the code's own documented behaviour, [hypothesis] = a guess
the run can support or refute.

## Why this exists

The G6 run picked the fly on balanced accuracy, but the fly warns on about
64% of test steps [measured] against a base rate of pain points near 15% [measured],
while the counters warn on about 33% of steps [measured] (all from results/offline-selection.json).
Balanced accuracy let each learner's own operating point decide how many
warnings it spent. A user pays for every wrong warning. This analysis puts all
learners at the same warning budget and counts what a wrong warning costs.

Violations prevented: **Paper Tiger** (a metric that is green while the user
drowns in false warnings) and **Silent Fallback** at the claim level (an
operating point chosen after seeing test numbers).

## What this analysis may and may not do

- It is exploratory and post-hoc. No decision rule is attached to it. It makes
  no p-values and no multiplicity correction over the 3 budgets and 3 costs.
- It cannot overturn, re-run or re-score G6. The verdict recorded in
  `results/offline-selection.json` stands as computed.
- If the numbers suggest that the fly is not better under a budget, that is
  reported next to the G6 result, not used to undo it.
- It makes no claim about speed of learning, or that the connectome makes the
  agent smarter.
- Confirmatory use: the budget, precision at the budget and net benefit are
  fixed as primary and secondary metrics in the Act 2 prereg before Act 2
  runs (see `prereg/AGENTS.md` and `prereg/AGENTS.md` note added in this task).

## Data, split and replay (unchanged from G6)

Same file, same task split (split seed 20261029, test fraction 0.3), same
replay order, same hub checkout rule, same labels (a filtered pain point at
steps t+1..t+5 of the same session), same learners: counters, the
mushroom-body network with the fly's published counts and random wiring (wiring
seeds 0, 1 and 2, learning rate 0.1), and similarity. Each learner replays the
train sessions online, then continues through the test sessions with what it
learned, exactly as in G6. Learning in both learners depends only on the
outcomes, never on whether a warning was issued, so the G6 operating settings
(counters minimum count, fly trouble threshold) change the flags and not the
risk scores below. The learners are therefore re-run once each, and the
risk score is read at every step.

## Risk score (evaluation only)

Each filler reports `Decision.risk`, higher meaning more likely trouble. It is
never rendered into a note to a model.

| learner | risk at a step |
|---|---|
| counters | number of earlier pain-point events (mined history plus learned) matching this step's files or command, after hub and scratch-file filtering; 0 when there are none or there is no history |
| fly | 1 minus the mean output weight of the active Kenyon cells (the score the trouble threshold is compared with); 0 when there is no history |
| similarity | none: it never flags, so it has no operating point |

## Budgeted operating point

For a budget b in {0.10, 0.15, 0.20}: take the risk of every TRAIN step from
the online train replay; the threshold is the observed risk value t such that
the share of train steps with risk at or above t is closest to b, ties going
to the higher t (fewer warnings). A step is flagged when its risk is at or
above t. The threshold is calibrated on TRAIN only, once per learner (per
wiring seed for the fly), and applied unchanged to the test steps. The flag
rate actually achieved on train and on test is reported, because discrete
counter risks cannot hit b exactly and because the test risk distribution can
move after the learner has seen all of train.

## Metrics at each budget

On the test steps, with TP = flagged and followed by a pain point in the next 5
steps, FP = flagged and not followed, FN = followed and not flagged:

- precision (PPV) = TP / (TP + FP)
- recall (TPR) = TP / (TP + FN)
- flag rate achieved = (TP + FP) / steps
- net benefit per 100 steps = 100 * (TP - c * FP) / steps, for the false-alarm
  cost c in {0.5, 1, 2}: one wrong warning costs c times what one right warning
  gains. c is an assumed exchange rate, not a measured one. [hypothesis]
- Reference floor: warn on every step (precision equals the base rate, recall 1)
  and warn on none (net benefit 0), printed in the same table.
- Differences (seed-averaged fly minus counters) for precision, recall and each
  net benefit, with the same intervals.

The fly row is the mean of the three wiring seeds' per-task counts (as in G6),
each seed with its own TRAIN threshold; each seed is also listed. The counters
row is printed beside every fly row. Similarity is listed as "no flags (recall
only)" with its recall@3 from the same replay; it has no precision.

## Intervals

Task-level percentile bootstrap, 2,000 draws, seed 20261029, multinomial
resampling of the test tasks (a task's attempts are not independent), the
same draw scheme as G6, 95% interval from the 2.5 and 97.5 percentiles [established]. A
draw with no warnings has undefined precision; such draws are counted and
reported, and the percentile uses the defined ones.

## Outputs

`results/warning-budget-exploratory.json`: thresholds, achieved train and test
flag rates, counts, metrics with intervals, differences, and the table as a
list of short row strings. Counts, ids and labels only. The table is copied
into this file under "Results" after the run, tagged [measured]. The run is
`scripts/offline/run_warning_budget.py` on the CPU host, with at least 11
cores left free, no GPU, no docker.

## Process rules

- This file is committed before any budget metric is computed on the test
  split. Train-only smoke runs of the new code are allowed before it.
  [measured at freeze: the commit of this file precedes the first test-split run]
- A crash or defect fix after the freeze is a dated amendment below, committed
  before the re-run.

## Results

(Filled in after the run.)
