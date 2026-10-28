# Pre-registration: does step text raise the ceiling? (T49)

**FROZEN 2026-10-28.** Committed alone, before any metric of this run exists on the 20 pool
scoring repositories. After the freeze only a dated amendment may change anything, and an
amendment cannot change the data, split, text, embedder, rows, hyperparameter rules, metric or
decision rule below.

Label: **gate on re-used data, not a scored claim.** The 20 pool scoring repositories (pool
fold 0) were already used in exploratory work (T46, T47); this run gates further learner tuning,
it does not claim a fresh result.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Question

The MLP ceiling probe ties the logistic regression on the 86 features and precision sits near
0.30 for every row, counters included [measured] (`results/fly-ablation-exploratory.json`). The
86 features are bucketed counts plus 14 hashed tokens, with no error or output text
[established]. [hypothesis] The limit is the input, not the learners: an embedding of each
step's text lets a learner predict trouble better. If the bar below is not met, learner tuning
stops and the run says so plainly. The classifier stays the live warner until this probe says
otherwise.

## Data and split

The 100-repository pool of `results/repo-pool.json`, exactly as T47 [established]: pool fold 0
(20 repositories) is scored, folds 1 to 4 (80 repositories) train, in pool order. Sessions in
the seeded replay order (`selection.replay_order`, seed 20261029), labels and the 86 features
from one counters replay per repository (`run_repo_curve.warm`), empty references and no hub
filter, as T46 and T47.

**Label** [established, by construction in `symbiont.eval.offline`]: a step is "followed by
trouble" when a filtered pain point is stamped at one of the next 5 steps of the same session
(steps t+1 to t+5, never step t). Every miner signal stamps a pain point at the step that
completes it (the failed command itself, the reworked edit, the last loop step; blast radius, the one signal stamped at an earlier step, cannot fire without references), so a step's
own failure never makes its own label true. The step's own command and output are therefore
information available when the note would be given, as the 86 features already read the step's
exit code; the text below uses the current step and nothing after it.

## Step text and embedding

Per step (`scripts/offline/step_text.py`): the action (for a command `$ ` and the command cut to
200 characters; otherwise the record kind and its files, cut to 200 characters) and a snippet of
the observation (whole when short, else its first 250 and last 250 characters) [established].
Embedded by `sentence-transformers/all-MiniLM-L6-v2` (384 dims, public weights) through
`fastembed` 0.9.1 on the CPU (`scripts/offline/embed_steps.py`), cached under `data/`; the text
is never printed or logged [established]. Nothing under `src/` imports the embedder.

## Rows

All four fit on the 80 training repositories only, frozen, scored on the 20 scoring repositories:

| row | label | inputs | model |
|---|---|---|---|
| counters | reference | none | `Counters(min_count=1)` through the real replay over the 80 repositories |
| logistic old | reference | 86 old features | class-weighted batch logistic regression |
| MLP old | reference | 86 old features | the T47 MLP ceiling probe (64 tanh units plus skip, input gain, Adam), wiring seeds 0, 1, 2 |
| logistic old+text | under test | 86 + 384 | as logistic old |
| MLP old+text | under test | 86 + 384 | as MLP old, wiring seeds 0, 1, 2 |

**Hyperparameters, inside TRAIN only** [established]: the tuning slice is the last eight of the
80 training repositories in pool order. Logistic penalty: from the grid 0.1, 1, 10, 100, 1000,
the one with the highest ROC AUC on the tuning slice after a fit on the other 72 (ties to the
stronger penalty), then refit on all 80. MLP: fit on the 72, stopped early on its weighted log
loss on the 8 (T47's rule: 30 epochs at most, patience 3); hidden width fixed at 64.

## Scoring

Option A by cross-validation grouped by scoring repository and the repository bootstrap of T47
(`note_cost_report.report`, seed 20261029, the same draws for every row, so differences are
paired) [established]. Each row is scored in the fly's slot with the counters row beside it and
logistic old in the classifier's slot. The bar is read at T47's headline option
`a_heads_up_gain_1`; `a_tiers_boundary_budget` is reported too. Also reported per row: ROC AUC
and precision in the riskiest 1% of scoring steps (seed-averaged over wiring seeds for MLP rows) [established].

## Decision rule (copied verbatim from the owner's dispatch; only the claim tag is added)

- PASS if MLP(old + text) minus logistic(old) is at least +0.03 net value per 100 steps, paired task-bootstrap 95% lower bound above 0, AND ROC AUC rises by at least 0.03. [established]
- Otherwise FAIL: report "the step text does not raise the ceiling enough to justify more learner tuning" as the headline.
- The verdict word (PASS/FAIL) is the first line of the results file. Note that the 20 pool scoring repositories were already used in exploratory work (label: gate on re-used data, not a scored claim).

Here "task" in the bootstrap is the repository, as in T47 [established]. "ROC AUC rises" means
the seed-averaged ROC AUC of MLP old+text minus the ROC AUC of logistic old on the scoring
steps. The run is `run_text_ceiling.py --scored --prereg prereg/2026-10-28-text-ceiling.md`;
the runner refuses `--scored` without this frozen file. Results: `results/text-ceiling.json`,
counts, ids and labels only.

## Before the freeze

A rehearsal (`--rehearsal`: pool fold 1 scored, folds 2 to 4 train; no fold 0 label entered any
metric) checked the pipeline before this file was frozen, and its numbers were seen [measured].
It changed nothing above: the bar is the owner's, verbatim, and the text, rows and
hyperparameter rules were written before it ran. Its output stays under the run directory,
never in `results/`.

## Spend

None: CPU only, local, no API calls [established].
