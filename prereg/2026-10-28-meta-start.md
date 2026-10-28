# Pre-registration: a meta-learned start on repositories never seen (T39)

**FROZEN 2026-10-28.** Committed alone, before any metric on the scoring repositories exists. After the freeze only a dated amendment may change anything, and an amendment cannot change the data, split, seed, labels, prices, budget, cooldown, grids, windows, metric or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

Owner-proxy rulings applied: `.superpowers/rulings/2026-10-28-meta-start.md` (13 items) and the controller rulings of 2026-10-28 (first 10 outcomes = first 10 sessions; Reptile grid to 0.01; calibrator rate on validation; primary scored set Pillow, dvc, conan; pool fold 0 secondary, re-used).

## Amendments

(none at freeze)

## Question

T46 found that one batch logistic classifier on the same 86 per-step features earns about 0.19 net value per 100 steps on 20 pool repositories, while counters, the fly and DenseNet, learning online, earn 0.04 to 0.08 and do not improve with more training repositories [measured] (`results/note-cost-repo-curve.json`). Spec 4.5 asks whether a filler whose starting point (readout start plus calibrator) is meta-trained across many repositories adapts better from the first outcomes on a repository it has never seen. No claim about how quickly anything learns; the fly is "a learner built on the fly's real circuit" with random wiring at the fly's published counts.

## Data

- **Primary scored set: `python-pillow/Pillow`, `iterative/dvc`, `conan-io/conan`**, exactly as T46 pinned them: `nebius/SWE-rebench-openhands-trajectories` at revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`, every task, exported by `scripts/datasets/export_nebius_repos.py export-held-out` at commit `d860b8e`; task metadata from `nebius/SWE-rebench` at revision `89cdfbab4ab1bd8f5a658bb212d1b63624f4f881`. A trajectory the OpenHands reader refuses is dropped before anything else and counted (1 Pillow trajectory [measured]). Hubs and references from T46's checkout of the median-created TRAIN task's base commit (cutoff 0.5; Pillow `Tests/helper.py`, dvc none, conan `conans/test/utils/tools.py` [measured], identical to the T46 scored run's log). Labels as T46: a filtered pain point (hub filter and blast radius) within the next 5 steps of the same session.
- Each primary repository is replayed **whole**, from empty history, every task, sessions in T46's seeded replay order. `split_by_task` is used only to name T46's hub task; there is no TRAIN/TEST split, because every row adapts online from zero. None of the three was read by any T39 training or smoke code. Before the freeze T39 read them only to count them (below) and to build the episode file the rows replay (features, labels and the counters' risks, by `scripts/offline/meta_start_held_out.py`); no risk of any other row and no metric was computed.
- **Secondary scored set: pool fold 0** (20 repositories of `results/repo-pool.json`), labeled "re-used: T46's exploratory curve scored cold rows here; may not decide". Pool labels have no hub filter and no blast radius (no checkout).
- Meta-training: 70 training repositories; 10 validation repositories (seeded, numpy seed 20261028) choose every setting; fold 0 is never trained on. The classifier fits on the 80 non-scoring pool repositories.

### Counts (recorded before any metric) [measured]

| set | repository | refused | tasks | sessions | steps | early sessions | early steps | early tasks |
|---|---|---|---|---|---|---|---|---|
| primary | `python-pillow/Pillow` | 1 | 126 | 1,327 | 159,781 | 10 | 933 | 2 |
| primary | `iterative/dvc` | 0 | 68 | 846 | 96,772 | 10 | 1,225 | 2 |
| primary | `conan-io/conan` | 0 | 67 | 692 | 79,117 | 10 | 1,319 | 1 |
| secondary | pool fold 0 (20 repositories) | 0 | 95 | 917 | 96,457 | 200 | 20,662 | n/a |
| selection | validation (10 repositories) | 0 | n/a | 466 | 51,517 | 100 | 9,665 | n/a |

## What is meta-trained (spec 4.5)

Only the readout's starting weights and the calibrator (scale, bias) of each filler, through the `MetaLearnable` contract (`src/symbiont/core/meta.py`). Wiring, the fly's sparsity, DenseNet's hidden layer and the readout rates stay fixed (fly 0.1, DenseNet 0.1 as T46).

- Task: one training repository. Inner loop: the filler's own online rule over the repository's first 10 sessions, learning after each session as the replay does. Objective: mean weighted log loss per step (a false alarm costs 0.5 of a miss) of the calibrated probability at each step, from the start in force when its session began.
- Outer rules, both first-order: first-order MAML (Adam on the loss gradient at the in-force start; step sizes 0.001, 0.003, 0.01) and Reptile (move the given fraction toward the batch's mean adapted start; 0.01, 0.03, 0.1, 0.3). 8 repositories per outer step, at most 300 outer steps, a validation check every 5 outer steps, stop after 20 checks without improvement, seed = wiring seed. Jobs resume bit-identically from the last check.
- **Calibrator rate** from {0.05, 0.1, 0.2, 0.5}, a fixed setting of the filler, never self-tuned (controller ruling). One rate per filler: the rate whose best meta start has the lowest validation loss averaged over the three wiring seeds. It is shared by that filler's cold and meta rows, so H1 isolates the start. The adapting classifier chooses its own rate the same way (lowest validation early-window loss).
- Per filler and seed, at that rate: the (rule, step size, check) with the lowest validation loss is the meta start; the cold start (check 0) is a candidate, so "nothing helps" returns the cold start and is reported.
- Pinned before the freeze: the starts file `data/t39-starts.npz` has sha256 `ff14231121813e1ed248fffd0ed52d6e45cfb02e3c2a2e30777ebd951fa13866`, trained at code commit `2e44fd9` (jobs resumed bit-identically from checkpoints written at `19310a0`; the summary file was written after the checkout moved to `34a446b`, which changed no training code); its validation curves are `results/meta-start-training.json`, committed in `05045b5`. The chosen points [measured]: calibrator rate 0.05 for both fillers; every meta start is first-order MAML at step size 0.01, at check 205, 210, 250 (DenseNet seeds 0, 1, 2) and 270, 280, 300 (fly seeds 0, 1, 2); validation loss cold to meta: DenseNet 0.369 to 0.349, fly 0.370 to 0.350.

## Windows

Learning happens when a session ends, so a repository's first outcomes arrive session by session: the **early window is each repository's first 10 sessions** (controller ruling), 30 sessions on the primary set; the **late window** is every later session. They are scored and reported separately.

## Delivery, prices and thresholds

Option A from T46: boundary steps only (a failed command or an edit of a file this session already edited and applied), at most 2 notes per session, none within 5 steps of the last, two tiers. **Primary price:** a true note +1; a false warning -0.5; a false heads-up -0.25 (heads-up gain 1). **Thresholds:** per row, per window, per price, per wiring seed, chosen on the 10 validation repositories' replays (the same online-from-zero replay) over T46's 40-point quantile grid: the pair with the highest validation value per step, ties to fewer notes, silence unless a pair beats 0; then fixed. Nothing is fit on a scoring repository. The same thresholds score fold 0.

## Rows and labels

| row | label |
|---|---|
| warn never | floor (0 by construction) |
| a note at every allowed step (all warnings) | floor |
| counters, online from zero | reference |
| logistic: class-weighted, L2 1000, fit on the 80 non-scoring pool repositories, fixed | reference (a standard supervised baseline) |
| logistic + online calibrator: the same fit, its logit through the fillers' `Calibrator` from identity, `calibrator_step` after each session, at its validation-chosen rate | reference (the fixed classifier plus the fillers' online calibrator) |
| DenseNet cold start, wiring seeds 0, 1, 2 (mean of per-unit counts) | under test |
| DenseNet meta start, seeds 0, 1, 2 | under test |
| fly cold start, seeds 0, 1, 2 | under test |
| fly meta start, seeds 0, 1, 2 | under test |

Every filler row scores its calibrated probability (`trouble_probability`), so "fly cold" is not T46's raw-risk fly row. The counters row is printed beside both fly rows (QG-SCI-03). Per-seed rows are sensitivity.

## Metrics

- **Primary:** early-window net value per 100 steps at the primary price, pooled over the three repositories, with a 95% [established] percentile interval from 2,000 bootstrap draws (numpy seed 20261029) that resample units within each repository, the same draws for every row, so differences are paired. The unit is the task; in the early window it is the **session**, because each repository's first 10 sessions hold only 1 or 2 tasks [measured] and a task bootstrap would have no spread (conan: one task). Sessions of one task are not independent, so the early-window interval is too narrow [established]; this is disclosed, not corrected.
- Each repository on its own with the same draws restricted to its units. Precision and notes per session beside value for every row, with notes per 100 steps, false notes per session, heads-up share and the share of trouble spells that got a note (T46 wording). A sign-consistency tag across the three repositories is reported and never decides.
- Fold 0: the same rows, windows and prices, units = repositories, reported, never deciding.

## Hypotheses

- **H1 (primary, per filler):** [hypothesis] the meta start beats the cold start of the same filler in the early window (fly meta minus fly cold; DenseNet meta minus DenseNet cold). Two tests, each on its own interval.
- **H2:** [hypothesis] the meta start beats the adapting classifier (each filler, each window).
- **H3:** [hypothesis] whether the meta start reaches the fixed classifier (each filler).
- **H4:** [hypothesis] the adapting classifier does not beat the fixed classifier in either window (adapting minus fixed, interval not above 0).
- Expectation, informed by the smoke run and not blind: [measured, exploratory, 10 validation repositories that also chose the start] fly meta minus cold -0.054 [-0.108, -0.009]; DenseNet -0.036 [-0.067, -0.003]; adapting minus fixed classifier -0.122 [-0.212, -0.045] in the late window. Expectation [hypothesis]: H1 fails or ties for both fillers; H4 holds.

## Decision rule (exact)

1. H1 outputs one of three words per filler: `better` (lower bound of the early-window meta-minus-cold interval above 0), `tie` (interval includes 0), `worse` (upper bound below 0). The report's first line per filler is that word and the paired interval. **"The meta start is worse than the cold start"** is a registered verdict and is reported in those words. A `worse` or `tie` on the primary set is the result, whatever fold 0 says.
2. H2, H3 and H4 use the same three words on their paired intervals.
3. A meta start is recommended as the live start of a filler only if H1 is `better` for it AND its early-window interval is above 0 (it earns notes) AND its difference from counters is not `worse`.
4. If the adapting classifier's early-window value beats every meta-started filler (paired interval above 0), the report says so, and the classifier remains the reference to beat, whatever H1 says.
5. Best early-window row, if asked: candidates in tie order plainest first: counters, fixed classifier, adapting classifier, DenseNet cold, DenseNet meta, fly cold, fly meta; a row earns if its lower bound is above 0; the earner with the highest point estimate, unless it is not counters and its paired difference from counters is not above 0, in which case counters if counters earn, else none (T46 rules 1, 4, 5).
6. Multiple comparisons: H1 is two tests at 95% [established]; H2, H3, H4 add eight more intervals. No correction is applied (Known limits), and no secondary may decide.
7. No re-run after seeing the table, and no change of data, prices, budget, cooldown, grids, windows, calibrator rates, seeds, thresholds or starts after any scoring metric exists.

## T20 void trigger

If T20's placebo arm measures the cost of a wrong heads-up above 0.25 of a right one, every value-based verdict of this run, including the H1 comparison, is void, and a dated amendment declares the re-scoring.

## Sensitivity (reported, never decides)

- Heads-up gain 0.75 and 0.5 (false heads-up still -0.25); the heads-up cost curve 0.1 to 0.5 at gain 1 (T46 rows).
- The late window under every price.
- Per-seed rows and per-repository rows.
- Fold 0 (re-used).
- The validation curves of every (filler, seed, rule, step size, calibrator rate) in `results/meta-start-training.json`; the validation value per 100 steps beside the validation loss for the chosen points.

## Known limits

- The primary window is 30 sessions from 5 tasks, so power is low and a wide tie is the likely outcome [established]; the session unit understates the interval's width [established].
- The meta start was trained on the pool's hub-less labels and is scored on hub-filtered labels: the "never seen" test the spec asks for, and also a label shift.
- Ten validation repositories choose among 28 grid points per filler and seed plus four calibrator rates (selection noise); they also choose every threshold, and the classifier was fit on them, so its validation thresholds and calibrator rate are chosen in-sample.
- Loss and value disagreed in the smoke run [measured]; the selector is loss.
- The smoke numbers were known before the freeze; the expectation line is informed by them.
- Fold 0 is re-used. Ten intervals at 95% [established] without correction.
- The classifier is batch-fit; live, it needs a refit per project.
- The fly readout is not clipped to non-negative weights in the outer loop.
- "Fly cold" is calibrated, not T46's raw-risk fly row.
- The chosen points sit on grid edges, named here: the calibrator rate is the smallest of the grid (0.05), the first-order MAML step size is the largest (0.01), and fly seed 2 stopped at the 300-step cap. Per the owner-proxy ruling the grid is not extended.
- Both outer rules are first-order; the smoke run showed first-order MAML raising DenseNet's training loss [measured].
- The cue key (second half of the plan task) is deferred.

## Run host and spend

The Strix CPU (the full train moved there after the desktop dropped off the network), at most 10 workers (a third of its cores, shared with T46 and T47); the held-out episodes were built on the owner's laptop CPU from the same pinned export (sha256-checked against the Strix copy). No GPU, docker or paid calls. Spend: zero paid. The 168-job grid took about 25 minutes of wall clock in two parts (restarted once from its checkpoints to add a cell-code memo) [measured]; scoring is estimated at a few minutes [hypothesis].
