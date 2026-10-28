# Pre-registration DRAFT: a meta-learned start on repositories never seen (T39)

Status: DRAFT, not frozen. Nothing here may be run with `--scored`. After an owner-proxy review, a copy named `2026-10-28-meta-start.md` (the name `scripts/offline/run_meta_start.py` checks) is committed alone as the freeze, before any metric on the scoring repositories exists.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Question

T46 found that one batch logistic classifier on the same 86 per-step features earns about 0.19 net value per 100 steps on 20 unseen pool repositories, while counters, the fly and DenseNet, learning online, earn 0.04 to 0.08 and do not improve with more training repositories (1 to 80) [measured] (`results/note-cost-repo-curve.json`). Spec 4.5 asks whether a filler whose starting point (readout start plus calibrator) is meta-trained across many repositories adapts better from the first outcomes on a repository it has never seen. No claim about how quickly anything learns; the fly is "a learner built on the fly's real circuit" with random wiring at the fly's published counts.

## Data

- Pool: `results/repo-pool.json` (100 repositories, 4,621 trajectories, 512,191 steps [measured]), built by T46 before any T39 code existed. `python-pillow/Pillow`, `iterative/dvc` and `conan-io/conan` are held out for T46 and are never read; `tobymao/sqlglot` is excluded. `meta_split` raises if any of them is in the pool.
- Scoring repositories: pool fold 0 (20 repositories, 96,457 steps [measured]). Disclosure: T46's exploratory repository curve was scored on this fold, so its counters, fly, DenseNet and classifier numbers there are known; the meta-start rows and the adapting classifier row have never been computed on it [established] (by construction).
- Validation repositories: a seeded 10 (numpy seed 20261028) of the 80 others, for the outer step size, the outer rule and early stopping. Training repositories: the remaining 70.
- Each repository is replayed on its own, from empty history, sessions in T46's seeded replay order. Labels (pain point within 5 steps, no blast-radius signal and no hub filter, since no checkout is made), the 86 features and the leak rule as T46. Learners learn with false-alarm cost 0.5, as T36 and T46.

## What is meta-trained (spec 4.5)

Only the readout's starting weights and the calibrator (scale, bias) of each filler, through the `MetaLearnable` contract (`src/symbiont/core/meta.py`). Wiring, the fly's sparsity, DenseNet's hidden layer and every learning rate stay fixed (fly rate 0.1, DenseNet rate 0.1 as T46, calibrator rate 0.5).

- Task: one training repository. Inner loop: the filler's own online rule over the repository's first 10 sessions, learning after each session as the replay does. Objective: mean weighted log loss per step (a false alarm costs 0.5 of a miss) of the probability at each step, from the start in force when its session began.
- Outer rules, both first-order: first-order MAML (Adam on the loss gradient at the in-force start; step sizes 0.001, 0.003, 0.01) and Reptile (move the given fraction toward the batch's mean adapted start; 0.03, 0.1, 0.3). 8 repositories per outer step, at most 300 outer steps, validation every 20, stop after 5 checks without improvement, seed = wiring seed.
- Selection on validation only: per filler and wiring seed, the (rule, step size, check) with the lowest validation loss; the cold start (step 0) is a candidate, so "no meta start helps on validation" returns the cold start, and that is reported.

## Windows (spec 4.5)

Learning happens when a session ends, so a repository's first outcomes arrive session by session. The early window is each scoring repository's first 10 sessions (about 1,100 steps; the first session is decided wholly from the start); the late window is every session after the tenth. They are scored and reported separately.

## Delivery and value (option A, fixed from T46)

Boundary steps only (a failed command or an edit of a file this session already edited and applied), at most 2 notes per session, none within 5 steps of the last, two tiers. Primary value: a true note +1, a false warning -0.5, a false heads-up -0.25 (heads-up worth a right warning, `a_heads_up_gain_1`). Thresholds: picked by 5-fold cross-validation grouped by repository inside each window (`note_cost_select.task_folds`, seed 20261029), on the 40-point quantile grid; silence unless a pair beats 0 on the training folds.

## Rows and labels

| row | label |
|---|---|
| warn never | floor (0 by construction) |
| counters, online from zero on each repository | reference |
| logistic classifier: class-weighted, L2 1000, fit on the 80 non-scoring repositories, fixed | reference |
| logistic classifier + online calibrator: the same fit, its logit through the fillers' `Calibrator` from identity, updated by `calibrator_step` after each session | reference |
| fly cold start, wiring seeds 0, 1, 2 (mean of per-repository counts) | under test |
| fly meta start, seeds 0, 1, 2 | under test |
| DenseNet cold start, seeds 0, 1, 2 | under test |
| DenseNet meta start, seeds 0, 1, 2 | under test |

Every filler row adapts online from zero on each scoring repository, its risk being the calibrated probability (`trouble_probability`). The counters row is printed beside the fly rows (QG-SCI-03).

## Primary metric

Net value per 100 steps in the early window, pooled over the 20 scoring repositories, with a 95% [established] percentile interval from 2,000 repository-bootstrap draws (seed 20261029), the same draws for every row, so differences are paired.

## Hypotheses

- Primary (H1, per filler): [hypothesis] the meta start beats the cold start of the same filler in the early window: fly meta minus fly cold > 0, and DenseNet meta minus DenseNet cold > 0. Two hypotheses, each judged on its own interval; neither is pooled with the other.
- Secondary (H2, per filler): [hypothesis] the meta start beats the adapting classifier on the scoring repositories: meta start minus "logistic + online calibrator" > 0, in the early window and in the late window. This asks whether a meta-started filler adds anything beyond a strong global model that may also adapt.
- Secondary (H3): [hypothesis] whether a meta start reaches the fixed classifier (difference interval includes 0 or is positive).
- [hypothesis] Expectation, written before the run: H1 holds weakly or not at all, and H2 fails. The validation smoke run (`results/meta-start-smoke.json`) is the only evidence so far.

## Decision rule (exact)

1. H1 holds for a filler if the lower bound of its early-window meta-minus-cold interval is above 0; "tie" if the interval includes 0; "worse" if the upper bound is below 0.
2. H2 holds for a filler if the lower bound of meta start minus the adapting classifier is above 0 in that window.
3. A meta start is recommended as the live start of a filler only if H1 holds for it AND, in the early window, the meta-started filler's own interval is above 0 (it earns notes) AND it is not worse than counters (the difference interval is not entirely negative).
4. If the adapting classifier's early-window value beats every meta-started filler (paired interval above 0), the report says so, and the classifier remains the reference to beat, whatever H1 says.
5. No re-run after seeing the table and no change of data, prices, budget, cooldown, grid, windows or rule.

## Sensitivity (reported, never decides)

- Heads-up worth 0.75 of a right warning (`a_tiers_boundary_budget`).
- The late window under the primary value.
- Per-seed rows and the validation curves of every (filler, seed, rule, step size).

## Known limits

- The inner loop is long (a session is about 100 steps), so both outer rules are first-order approximations; the smoke run showed first-order MAML raising DenseNet's training loss [measured], which is why Reptile is in the grid.
- The fixed calibrator rate (0.5) re-fits the calibrator within one session; this limits how long any start's calibrator survives [hypothesis].
- The fly's multiplicative rule assumes non-negative weights; the outer loop does not clip them.
- Run host: the 5080 desktop CPU (WSL), no GPU, no docker; Strix CPU for building the episodes. No paid calls. Only counts, ids and labels leave the hosts.
- The cue key (the second half of the plan task) is deferred and not part of this run.
