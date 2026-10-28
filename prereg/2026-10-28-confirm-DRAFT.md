# Pre-registration: the fixed fly and the classifier on three new repositories (T48)

Status: DRAFT, not frozen. The freeze commit renames this file to
`prereg/2026-10-28-confirm.md` and changes only this status header.
After the freeze only a dated amendment may change anything, and an amendment
cannot change the data, shipping, settings, labels, prices, budget, cooldown,
metric or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Question

T47 found on the 100-repository pool that two changes faithful to the fly's circuit, projection-neuron gain control and a slow output compartment, roughly double the fly's net value (0.072 to 0.136 per 100 steps under option A), while a batch logistic regression stays ahead (0.187) [measured] (`docs/design/2026-10-28-fly-ablation.md`, `results/fly-ablation-exploratory.json`). On three repositories none of those runs read, which (learner, regime) earns notes, and does the fixed fly beat counters and tie or beat the classifier? If no learner earns notes, the product ships recall-only plus encourage notes (T42); that is a result and is reported plainly. No claim about how quickly anything learns; the fly is "a learner built on the fly's real circuit" with random wiring at the fly's published counts.

## Data

Scored set: `tox-dev/tox`, `dask/dask`, `pybamm-team/PyBaMM` from `nebius/SWE-rebench-openhands-trajectories` at revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`, every task, exported by `scripts/datasets/export_confirm_repos.py` (commit `1518544`), which calls the pinned exporter of commit `d860b8e` unchanged; task metadata from `nebius/SWE-rebench` at revision `89cdfbab4ab1bd8f5a658bb212d1b63624f4f881`. The set was declared in commit `47a3a4f`, from trajectory counts alone, before any T47 ablation run: the next three largest repositories after Pillow, dvc, conan, sqlglot, the four the reader refuses and the 100 pool repositories. No row of them was read by G6, T36, T46 or T47 [established].

A trajectory the OpenHands reader refuses (`read_each_row` returns a ReadError) is dropped before anything else and counted below, as T46 [established].

**No TRAIN/TEST split.** Nothing is fit on these repositories (every setting below is fixed from the pool), so every task is scored. Each repository is replayed on its own from the shipped state, history empty, sessions in the seeded replay order of the pool runs (`selection.replay_order`). Labels: a filtered pain point within the next 5 steps of the same session, mined with empty references and no hub filter, exactly as the pool labels the learners were shipped on (no repository checkout); 86 features and the leak rule as G6. Online learners learn with false_alarm_cost 0.5, as T36 and T47.

## Counts (recorded before any label, risk or metric)

Read through the OpenHands reader on the run machine, counts only (`run_confirm_scored.py counts`) [measured]:

| repository | trajectories refused by the reader | readable trajectories | tasks | sessions | steps |
|---|---|---|---|---|---|
| `tox-dev/tox` | 1 | 605 | 54 | 605 | 77,554 |
| `dask/dask` | 0 | 605 | 56 | 605 | 71,511 |
| `pybamm-team/PyBaMM` | 0 | 524 | 44 | 524 | 62,673 |

No session lacked a task id in any repository [measured]. Pooled: 154 tasks, 1,734 sessions, 211,738 steps [measured].

## Shipping (all fixed from the pool)

Every learner is shipped from the 80 training repositories of the pool (`results/repo-pool.json`, folds 1 to 4) in pool order, exactly as the T47 N = 80 runs, then replayed on each confirm repository:

| row | label | regime | shipped state | settings |
|---|---|---|---|---|
| warn never | floor | none | none | value 0 by construction |
| a note at every allowed step (all warnings) | floor | none | none | none |
| counters (`Counters(min_count=1)`) | reference | R1 | online over the 80 repositories (real replay) | thresholds below |
| logistic regression | reference | R1 (frozen) | class-weighted batch fit on the 80 repositories' features, L2 1000 (the committed T46 curve's value) | thresholds below |
| DenseNet combined | under test | R2, backprop refit | `DenseVariant`: 512 tanh units, fixed weights times 1/sqrt(86), readout over hidden activity and gained inputs, rate 1.0 decaying as 1/(1 + updates/20,000), trouble weight (1 - p)/p with p the 80 repositories' trouble share, input gain below; online over the 80 repositories; after each confirm session the whole network is refit on that repository's sessions so far (20 Adam steps, rate 0.01, L2 pull 10 toward the shipped weights) | wiring seeds 0, 1, 2; thresholds below |
| fly as is | under test | R1 | `Mushroom` (lr 0.1, 86 inputs, 5,177 cells, 7 inputs per cell, top 5%); online over the 80 repositories | wiring seeds 0, 1, 2; thresholds below [established] |
| fly combined | under test | R1 | `FlyVariant`: compartment rates 0.1 and 0.01, approach and avoid output neurons (reward side at 0.2 of the punishment rate), projection-neuron gain (each input centered and scaled by its mean and spread on the 80 repositories, capped at 3 spreads); online over the 80 repositories | wiring seeds 0, 1, 2; thresholds below |

R1: the learner's own per-step rule after each session ends; a batch model stays frozen. R2: after each session, a refit from the shipped state on the repository's sessions so far; the next session is scored with it. A learner only uses sessions before the one being scored [established] (by construction, `symbiont.eval.regime_replay`).

**Thresholds.** For each row and wiring seed, under each registered option, the (note, warning) pair is chosen by the T46 rule (the 40-point quantile grid of `note_cost_options.threshold_grid`, highest value per step, ties to fewer notes, silence if no pair beats 0) on that shipped learner's traces over the 20 pool scoring repositories (pool fold 0), and then fixed. They are committed in `results/confirm-shipped-settings.json` with this draft; the scored runner recomputes them and refuses to run if any differs. Primary-option values:

| row | seed | note at or above | warning at or above | pool value per 100 steps |
|---|---|---|---|---|
| counters | 0 | 3 | never | 0.080 [measured] |
| logistic regression | 0 | 0.628134 | never | 0.187 [measured] |
| DenseNet combined | 0 | 0.553825 | never | 0.148 [measured] |
| DenseNet combined | 1 | 0.833885 | never | 0.160 [measured] |
| DenseNet combined | 2 | 0.774248 | never | 0.145 [measured] |
| fly as is | 0 | 0.78133 | never | 0.082 [measured] |
| fly as is | 1 | 0.80987 | never | 0.084 [measured] |
| fly as is | 2 | 0.810761 | never | 0.081 [measured] |
| fly combined | 0 | -0.119194 | never | 0.141 [measured] |
| fly combined | 1 | -0.119433 | never | 0.142 [measured] |
| fly combined | 2 | -0.10651 | never | 0.140 [measured] |

Every row's primary choice is heads-ups only (no warning tier) [measured]. The fly combined risk is avoid minus approach output, so its threshold can be negative [established] (by construction).

## Delivery and prices (as T46)

- Boundary step: the step's record is a failed command (the miner's rule) or an edit of a file this session already edited and applied.
- At most 2 notes per session, spent online on the first qualifying steps; no note within 5 steps of the last.
- A note is a warning if risk is at or above the warning threshold, else a heads-up if at or above the note threshold.
- **Primary price:** a true warning +1, a false warning -0.5; a true heads-up +1, a false heads-up -0.25. The heads-up gain 0.75 and 0.5 rows and the heads-up cost curve (0.1 to 0.5 at gain 1) are reported and never decide.
- **T20 trigger:** if T20's placebo arm measures the cost of a wrong heads-up above 0.25 of a right one, the live-warner verdict of this run is void, and a dated amendment declares the re-scoring.

## Metrics (as T46)

- Primary: net value per 100 steps at the primary price, pooled over the three repositories, with a 95% [established] percentile interval from 2,000 task-bootstrap draws resampled within each repository (numpy seed 20261029), the same draws for every row, so differences are paired. Fly and DenseNet rows are the mean of per-task counts over wiring seeds 0, 1, 2.
- Each repository is reported on its own with the same draws restricted to its tasks.
- Precision and notes per session are printed beside value for every row, with notes per 100 steps, false notes per session, heads-up share and the share of trouble spells that got a note.
- Consistency tag: a learner whose per-repository point estimates disagree in sign is tagged "not consistent across repositories". The tag is reported and never decides.

## Decision rule (exact, primary price, pooled)

1. Candidates, in tie order, plainest first: counters, logistic regression (R1), DenseNet combined (R2), fly as is (R1), fly combined (R1). A candidate earns notes if the lower bound of its pooled net value interval is above 0.
2. If none earns: verdict `none`; ship E (recall-only plus encourage notes).
3. Otherwise take the earning candidate with the highest point estimate (ties by the order in 1).
4. If that candidate is not counters and the lower bound of its paired difference from counters is not above 0, the verdict is `counters` if counters earn, else `none`. Otherwise the verdict is that candidate.
5. "Better than counters" only if the paired interval excludes 0 on the positive side; "tie" if it includes 0; "worse" if entirely negative. The same wording for fly combined minus logistic regression, fly combined minus fly as is, and fly combined minus DenseNet combined. The fly question is answered by two of these: fly combined minus counters (beats counters only if better) and fly combined minus logistic regression (ties or beats the classifier if tie or better). A claim that the fly's circuit earns the gain needs fly combined minus DenseNet combined above 0.
6. No re-run after seeing the table and no change of data, shipping, settings, prices, budget, cooldown or rule.

## Sensitivity (reported, never decides)

- Heads-up gain 0.75 and 0.5 (the false heads-up still -0.25), each with its own pool-fixed thresholds.
- The heads-up cost curve: cost 0.1, 0.2, 0.3, 0.4, 0.5 at gain 1.
- Each repository on its own.
- Ranking AUC per row, pooled (threshold-free).

## Hypotheses (not claims)

- [hypothesis] The classifier earns the most (pool 0.187 [0.117, 0.262] [measured]).
- [hypothesis] Fly combined earns notes and beats fly as is and counters (pool 0.136 vs 0.072 and 0.063; minus counters 0.073 [0.029, 0.121] [measured]).
- [hypothesis] Fly combined ties or trails the classifier (pool minus classifier -0.051 [-0.109, 0.005] [measured]).
- [hypothesis] DenseNet combined R2 ties fly combined (pool 0.134 vs 0.136 [measured]).

## Disclosures

- The fly variant was chosen on the pool after one rerun: the first full T47 run used an uncapped input gain (a rare flag was scaled to about 200 spreads and the combined DenseNet readout diverged) and a classifier L2 of 100 instead of the T46 curve's 1000; the 3-spread cap and L2 1000 were fixed, then every row was rerun, and "fly combined" was picked from that rerun [established] (`docs/design/2026-10-28-fly-ablation.md`, Caveats). Uncapped, fly combined earned 0.119 on the pool [measured].
- A simpler fly (gain plus slow rate only) tied fly combined on the pool at 10 and 80 repositories; it was added after the first run and is not registered here [established].
- The thresholds are chosen on the same 20 pool scoring repositories on which the variants were compared; the confirm repositories were declared before any of that [established].
- One AUC-only fly screen on the pool scoring fold ran before the confirm set was declared; it read no confirm repository [established].
- The ship step's first run gave learners each other's thresholds (a stack cache keyed by object id); it was fixed in commit `054505a` and rerun before this draft; no confirm repository was read by it [established].

## Known limits

- Labels carry no blast-radius signal and no hub filter, unlike T46, to match the labels the learners were shipped on [established] (by construction).
- Five candidates are tested at 95% without multiplicity correction [established] (by construction).
- Thresholds are not refit per repository: a learner whose risk scale shifts on a new repository is priced at the pool's thresholds, as a shipped product would be [established] (by construction).
- The classifier is frozen (R1); T47 found per-project refits lower its value on the pool (0.142) [measured].

## Estimated spend

Zero paid calls. CPU only, on the laptop (at most 10 worker processes) or the Strix (at most 8), no GPU or docker: about 30 to 60 minutes [hypothesis] (the T47 main run took 13 minutes on the laptop for 96,457 scoring steps with R2 refits; the confirm set has 211,738 steps [measured]).

## Amendments

(none at freeze)
