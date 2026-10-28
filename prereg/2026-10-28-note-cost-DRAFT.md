# Pre-registration DRAFT: boundary heads-ups on fresh repositories (T46)

Status: DRAFT, not frozen. Nothing here may be run with `--scored`. The owner decides
the data question below, then a copy without "-DRAFT" is committed alone as the freeze,
before any metric on the new repositories exists.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Question

T36 found no learner that earns a warning when every warned step is its own alarm at c = 0.5 [measured]. Does any learner earn notes when notes are spent the way a hook would spend them: only at boundary steps, at most 2 per session, a 5-step cooldown, in two tiers? The design and the TRAIN-only exploration are in `docs/design/2026-10-28-note-cost.md` and `results/note-cost-exploratory.json`. If no learner earns notes, the product ships recall-only plus encourage notes (T42); that is an acceptable result and is reported plainly. No claim about how quickly anything learns; the fly is "a learner built on the fly's real circuit" with random wiring at the fly's published counts.

## Data (owner's decision 2026-10-28: hold these out)

The three repositories with the most trajectories in `nebius/SWE-rebench-openhands-trajectories` after `tobymao/sqlglot`, chosen by that rule before any of their rows is exported: `python-pillow/Pillow` (1,328 trajectories, 126 tasks), `iterative/dvc` (846, 68), `conan-io/conan` (692, 67) [measured] (a count of the repo column only). None was read by G6, T36 or T46. Each repository is exported with `scripts/datasets/export_nebius_sqlglot.py` generalized to a repo argument, split by task (test fraction 0.3, seed 20261029), and replayed on its own: TRAIN online, then TEST online with what was learned; only TEST steps are scored. Hubs per repository from the median-created TRAIN task's checkout, cutoff 0.5, as G6. Labels, window (5 steps), 86 features and leak rule as G6. Learners learn with false_alarm_cost 0.5, as T36.

Fallback if the owner declines new downloads: sqlglot with a new split seed (20261030), declared here, labeled "re-use of data the owner has seen"; its numbers are not independent of T36 [established] (by construction).

## Delivery and value (fixed from the T46 design; no grid on test)

- Boundary step: the step's record is a failed command (the miner's rule) or an edit of a file this session already edited and applied.
- At most 2 notes per session, spent online on the first qualifying steps; no note within 5 steps of the last.
- A note is a warning if risk is at or above the warning threshold, else a heads-up if at or above the note threshold.
- Value: a true warning +1, a false warning -0.5; a true heads-up +1, a false heads-up -0.25. A note is true when a filtered pain point follows within 5 steps.
- Thresholds: on each repository's TRAIN online risks, over the 40-point quantile grid of `note_cost_options.threshold_grid`, the pair with the highest TRAIN value per step; ties to fewer notes; silence if no pair beats 0. DenseNet's rate from {0.1, 0.3, 1.0} jointly with the thresholds. Choices are written to the results file.

## Rows and labels

| row | label |
|---|---|
| warn never | floor (value 0 by construction) |
| a note at every allowed step (all warnings) | floor |
| counters | reference |
| logistic regression: class-weighted, L2 strength from {0.1, 1, 10, 100, 1000} and thresholds picked by grouped cross-validation inside each repository's TRAIN, batch-fit on that TRAIN | reference (a standard supervised baseline) |
| fly, wiring seeds 0, 1, 2 (mean of per-task counts) | under test |
| DenseNet, wiring seeds 0, 1, 2 (mean of per-task counts) | under test |

The counters row is printed beside the fly row (QG-SCI-03).

## Primary metric

Net value per 100 TEST steps, pooled over the three repositories, with a 95% [established] percentile interval from 2,000 task-bootstrap draws resampled within each repository (numpy seed 20261029), the same draws for every row, so differences are paired.

## Decision rule (exact)

1. A learner earns notes if the lower bound of its net value interval is above 0. The candidates are counters, the classifier, fly and DenseNet.
2. If none does: verdict `none`; ship E (recall-only plus encourage notes).
3. Otherwise take the earning learner with the highest point estimate (ties: counters, then the classifier, then DenseNet, then fly).
4. If that learner is the fly, DenseNet or the classifier, counters also earn, and the lower bound of its difference from counters is not above 0, the verdict is `counters`.
5. "Better than counters" only if the paired interval excludes 0 on the positive side; "tie" if it includes 0; "worse" if entirely negative. A claim that the fly's circuit earns the gain needs fly minus DenseNet above 0.
6. No re-run after seeing the table and no change of data, prices, budget, cooldown, grid or rule.

## Sensitivity (reported, never decides)

- Heads-up gain 0.75 and 0.5 (the false heads-up still -0.25).
- Every learner started from its state after the 100-repository pool (classifier fit on the pool plus each repository's TRAIN).
- One tier only (every note a warning at c = 0.5).
- Option B (per spell) and C (budget 1, 2, 3 with conformal risk control at 0.25 of the budget).
- The decision curve of the per-step rule over c in 0.1 to 1.0.
- Each repository on its own.

## Hypotheses (not claims)

- [hypothesis] The classifier earns the most; counters and the fly earn notes and tie; DenseNet does not beat counters (TRAIN-CV: classifier 0.173 [0.149, 0.199], counters 0.090 [0.061, 0.121], fly 0.070 [0.044, 0.098], DenseNet 0.061 [0.037, 0.086] per 100 steps [measured]).
- [hypothesis] A start trained on the pool (`results/repo-pool.json`) does not help the online learners (repository curve flat or falling [measured]); it is reported as a sensitivity row, never decides.
- [hypothesis] Almost every note is a heads-up: no learner reaches 0.33 precision at boundaries.
- [hypothesis] The verdict flips to `none` if a heads-up is worth 0.5 of a warning.

## Known limits

- The heads-up price (-0.25 against +1) is the brief's value and was preferred after TRAIN exploration showed it decides the outcome; this run on unseen repositories is the guard against that choice [established] (by construction). T20's placebo arm should measure it.
- Fly and DenseNet constants were set on sqlglot; they are not re-tuned per repository.
- Run host: Strix CPU, no GPU, no docker. No paid calls. Only counts, ids and labels leave the host.
