# Pre-registration: offline selection of the live warner with penalized warnings (T36)

**FROZEN 2026-10-27.** Committed alone, before any test-split metric of this
run exists. After this commit only a dated amendment may change anything, and
an amendment cannot change the split, seed, labels, metric, cost, grids,
operating-point rule or decision rule below. This file re-asks the question of
`prereg/2026-10-29-offline-selection.md` (G6) under the owner's ruling that a
wrong warning costs something; it does not edit G6 and does not re-open its
recorded outcome.

Claim tags: [measured] = observed in our own run, [established] = known
from the literature or the code's own documented behavior, [hypothesis] =
a guess the run can support or refute.

## Question

Which learner, if any, should warn live? G6 ranked learners on balanced
accuracy, which let each learner pick its own warning rate; the fly flagged
about 64% of test steps [measured] (results/offline-selection.json). Here every
learner is judged on net benefit: a true warning gains 1, a false warning
costs c. If no learner beats never warning, the product ships recall-only with
no warnings until a learner earns it. That is an acceptable result and is
reported plainly. The run makes no claim about how quickly anything learns and
no claim that the connectome makes the agent smarter; the fly here has random
wiring with the fly's published counts.

## Controller rulings (fixed by the owner's controller, recorded here)

- Primary objective: net benefit per step on the held-out test split,
  NB = (true warnings - c * false warnings) / steps, with c = 0.5. Break-even
  precision is c / (1 + c) = 0.33 [established, algebra].
- Sensitivity: c = 0.25 and c = 1.0, reported with the same intervals. They
  carry no decision; only c = 0.5 decides.
- Operating point: each learner's warning threshold is chosen on the TRAIN
  split to maximize net benefit at the c in question, then frozen for test.
  Nothing is tuned on test.
- Placeholders from T38 (DenseNet hidden size, learning rate, threshold) are
  fixed below from TRAIN-split choices, never from test.

## Process rules

- No test-split metric is computed before this file is committed. Every run
  before the freeze (unit tests on synthetic fixtures, a smoke run with
  `--smoke-train-only`) touches train tasks only.
- After the freeze, a crash or bug fix is a dated amendment file committed
  before the re-run (`Amends: prereg/2026-10-28-penalized-selection.md`). It
  cannot change the split, seed, labels, metric, costs, grids, operating-point
  rule or decision rule. A re-run without an amendment is not allowed.
- The runner (`scripts/offline/run_penalized.py`) refuses `--scored` unless
  this file is committed and unchanged (`require_frozen`); the commit and
  sha256 go into `results/penalized-selection.json`.

## Data, split, labels and replay (unchanged from G6)

Same file (`data/nebius-openhands/sqlglot.jsonl`, 2,678 trajectories on 275
sqlglot tasks), same task split (test fraction 0.3, seed 20261029, by task id),
same replay order, same hub checkout rule and hub cutoff 0.5, same labels (a
filtered pain point at steps t+1 through t+5 of the same session), same 86
features, same leak rule (history holds finished sessions only). Each learner
replays the TRAIN sessions online, then continues online through the TEST
sessions with what it learned; only test steps are scored. See G6 for the
wording of each rule. The test split here is the one G6 and the exploratory
budget analysis already looked at; this run is therefore a second use of that
split, and its numbers are not independent of what the owner has seen
[established, by construction].

One change to replay, forced by the ruling: every false-alarm outcome a
learner learns from carries false_alarm_cost = 0.5 (`ReplayContext
.false_alarm_cost`; G6 used the balanced 1.0). It is fixed at 0.5 for every
sensitivity row: the c = 0.25 and c = 1.0 rows re-choose the threshold on
train and re-count test, they do not re-train the learners.

## Rows and labels

| row | label | warns when |
|---|---|---|
| warn never | floor | never; NB is 0 by definition |
| warn on every step | floor | always (printed for context) |
| counters | reference | risk at or above the train-chosen threshold; risk is the count of earlier matching pain-point events |
| similarity | reference | never (it has no risk score); recall@3 only; its NB is 0 and it cannot win |
| fly (`Mushroom`) | under test | risk at or above the train-chosen threshold; risk is 1 minus the mean output weight of the active cells |
| DenseNet | under test | risk (calibrated trouble probability) at or above the train-chosen threshold |

The counters row is always printed beside the fly row, and the results file
refuses a fly row with no counters row (QG-SCI-03). The fly and DenseNet rows
are the mean of the per-task counts over wiring seeds 0, 1 and 2, each seed
with its own train choices (as G6 averages the fly); each seed is also listed.
A flag in this run is "risk >= threshold", not `Decision.trouble`.

## Parameters, chosen on TRAIN only

For a learner and a cost c, the TRAIN risks are those of the online TRAIN
replay (each step's risk is read before the learner sees that step's outcome).

- Threshold: over every distinct TRAIN risk value t, NB_train(t, c) is the net
  benefit per step of flagging risk >= t. The chosen t is the maximizer; ties
  go to the higher t (fewer warnings). If the best NB_train is 0 or below, the
  threshold is "never" and the learner warns on no test step. (`best_threshold`.)
- Counters: no other parameter (the min_count of G6 is subsumed by the
  threshold on the count).
- Fly: learning rate 0.1 and random wiring as in G6, wiring seeds 0, 1, 2;
  the G6 trouble_threshold grid is replaced by the risk threshold above.
- DenseNet: hidden layer of 128 tanh units (the T38 constant, not searched),
  readout learning rate chosen per wiring seed from {0.1, 0.3, 1.0} as the one
  with the highest NB_train at its own best threshold (ties to the first
  listed); the T38 rate 1.0 is a placeholder, not a result. Wiring seeds 0, 1, 2.
- Every choice above is made separately for c = 0.5 (decides), 0.25 and 1.0.
- All choices are written into the results file under `chosen_on_train`.

## Metrics and intervals

- Primary: NB per step at c = 0.5 on the test split, per row, with a 95% [established]
  percentile bootstrap interval: 2,000 resamples of the test tasks
  (multinomial over tasks, as G6), numpy seed 20261029, the same draws for every
  row, so differences are paired. Displayed per 100 steps as well.
- Secondary: precision, recall, flag rate; NB at c = 0.25 and 1.0; recall@3
  for the learners that recall. A bootstrap draw with no warnings has undefined
  precision; such draws are counted and the interval uses the defined ones.
- Paired differences with the same intervals: fly - counters, DenseNet -
  counters, fly - DenseNet.

## Decision rule (exact, c = 0.5)

1. A learner beats warn-never if the lower bound of its NB interval is above 0.
   The candidates are counters, fly and DenseNet. Similarity warns never and is
   not a candidate.
2. If no candidate beats warn-never: the verdict is `none`, the product ships
   recall-only with no warnings, and no further comparison is acted on.
3. Otherwise take the candidate that beats warn-never with the highest point
   estimate of NB (ties: counters, then DenseNet, then fly).
4. If that candidate is the fly or DenseNet, counters also beat warn-never, and
   the lower bound of its difference from counters is not above 0, the
   verdict is `counters` (a tie is reported as a tie). Otherwise the verdict is
   the candidate of step 3.
5. The fly is called better than counters only if the interval of fly -
   counters excludes 0 on the positive side; if it includes 0 the report says
   the two tie; if it is entirely negative the report says the fly is worse.
   The same wording applies to DenseNet - counters and fly - DenseNet. A claim
   that the fly's circuit earns the gain needs fly - DenseNet to exclude 0 on
   the positive side.
6. No other outcome, no re-run after seeing the table, and no change of c,
   grids, split, seeds or this rule. The verdict is recorded as the T36
   outcome in `results/penalized-selection.json`.

## Hypotheses (not claims)

- [hypothesis] No learner beats warn-never at c = 0.5: break-even precision is
  0.33, and G6 saw precision near the 0.15 base rate for the fly.
- [hypothesis] If one does, counters and the fly tie, and DenseNet ties both.
- [hypothesis] The thresholds chosen on train are too permissive on test
  because test risks shift after the learner has seen all of train.

## Known limits (stated before the run)

- Parallel attempts at one task are next to each other in replay order, so an
  earlier attempt teaches a later one; the bootstrap resamples tasks so
  attempts stay together.
- The 5-step label window and the unit costs are assumptions of the metric,
  not facts about users [hypothesis]. c is an exchange rate chosen by the owner.
- Run host: Strix CPU, no GPU, no docker. Spend: no paid calls. SWE-chat data
  is not used and nothing but counts, ids and labels leaves the host.

## Amendments

(none at freeze)
