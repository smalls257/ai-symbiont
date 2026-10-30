# Pre-registration: Plug round 3, a pairwise judge over the ranker's shortlist (PLUG-JUDGE)

**FROZEN 2026-10-29.** Code pinned at `b057607` (this commit's parent; its code is 98ecc6b's; `plug_r3_run.py check` enforces it). Committed alone at the freeze, before the judge trained under it answers any validation or scored item. After the freeze only a dated amendment may change anything, and an amendment cannot change the data, split, training mix, scorers, metric, gates or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

Round 2 (`prereg/2026-10-29-plug-sit-cuda.md`) closed on validation with no scored run (`docs/research/2026-10-29-plug-round2-close.md`); it stays reported as it is. This round's design follows the exploratory round 3 (`docs/research/2026-10-29-plug-round3-exploratory.md`, `results/plug-r3-exploratory.json`, `results/plug-r3-points.json`).

## Amendments

(none at freeze)

## Question

A coding agent is in a situation: a command, a file and an error. A lexical ranker shortlists the 10 stored lessons that best match it. A judge, Llama 3.2 1B fine-tuned for one yes-or-no question, scores each shortlisted lesson: does it apply? If the top score (the mean P(yes) of three seeds) clears a threshold fitted on validation repos, the agent receives that lesson's stored note, verbatim; otherwise it receives nothing. On 40 repos neither has seen, does the judge pick the applicable lesson more often than the ranker with its own fitted threshold, while staying within the safety limits? Every applicable lesson in a scored item was added to the store after the judge was frozen and was never a training row [established, by construction]. The judge never writes a lesson, so it cannot invent one. No speed-of-learning words.

## What the exploration already saw (validation repos only)

- **Ranker coverage.** The ranker's top 10 hold the applicable lesson for every validation situation [measured].
- **The judge it measured is not this round's judge.** The numbers below come from a judge trained on 618 rows (309 yes, 309 no) without rewordings or habit rows [measured]. This round's training mix below has never been trained.
- **Judge 1B, 5-versus-5.** At a threshold fitted on 5 validation repos, it picked 0.786 on the other 5 with precision 0.767, but wrong pick there was 0.119, over the 0.05 limit: the fit did not transfer [measured]. The number to quote is not 0.79. Across all 10 repos its best point within the limits picks 0.47 [measured].
- **Two operating points on the 5 held-out repos** (read from those repos' own curve, not a transfer test; 42 applicable situations): at the lowest threshold with wrong pick at most 0.05 it answers 0.26 of applicable situations, Wilson interval 0.15 to 0.41, with precision 1.0; at silence at least 0.90 it answers 0.64, interval 0.49 to 0.77, picks 0.60 and has wrong pick 0.06 [measured].
- **3B.** The 3B judge picked 0.60 against the 1B's 0.79 at their 5-repo thresholds, and 0.18 against 0.47 at their best points within the limits [measured]. Its training matched the 1B's: 463 steps, peak learning rate 1e-4 with cosine decay and 20 warmup steps, no early stop, LoRA rank 16 and scale 2 on all seven projections, batch 4, the same chat template; its final loss (0.067 to 0.092) matched the 1B's (0.070 to 0.095) [measured]. No setting was wrong, so 3B is not rerun and not in this round.
- **The ranker alone** answers everything: pick 0.81, silence 0 [measured].
- **The thresholded ranker** on all 10 validation repos (code smoke test of `plug_r3_run.py fit`): lowest safe threshold 15.0, pick 0.157, silence 0.928, wrong pick 0.042 [measured]. It is deterministic, so the validation fit will return the same point. Validation top scores run from 2.71 to 19.92, inside the 0 to 30 grid [measured].
- **Power on the old judge.** The MDE formula below gives 0.22 on the old judge's validation gains over the thresholded ranker [measured], over the 0.10 line.
- **V2 cannot be made safe.** Round 2's V2 reader, thresholded on its own confidence, cannot be made safe [measured], so it is not a reference here.

## Data and split

- **Lessons, pins and plan.** As in round 2 (`plug_round2.py`, `plug_r2_score.PINNED`; pool index sha256 a14f22f0...). `plug_r3_run.py check` runs `plug_r2_score.check` with this prereg's name and refuses any other prereg, input or code commit.
- **Scored repos.** The 40 scored repos of round 2's plan (165 lessons, 330 items [measured]), named in `prereg/2026-10-29-plug-sit-cuda.md`. No answer on them exists, because round 2 stopped before its scored run [measured]. `check_plan` refuses any other plan.
- **Validation repos.** The 10 repos of the a3 rerun: 83 lessons, 166 items [measured]. The thresholds are fitted on all 10.
- **Meta-training repos.** Every other repo of the pool: 60 repos, 309 lessons [measured], including round 2's 11 meta-joining repos. `plug_r3.check_meta` refuses any list whose sha256 (sorted names, newline-joined) is not cdf6df15b59e6ff5... (`plug_r3.META_REPOS_SHA256`).
- **Split checks.** `plug_r3.check_splits` raises on any repo or lesson id shared by meta-train, validation and scored (each pair), and on a habit repo inside any of them. It prints how many lessons share a failure key with a meta-train lesson: 5 of validation's 83 and 5 of scored's 165 [measured].
- **Items.** Each lesson gives one pick item (its situation and 60 lessons including it) and one silence item (the same without it), so every repo has both kinds [established, by construction]; `plug_r3.per_repo` raises otherwise. Situations are written from the lesson's own fields (`plug_situation.situation_of`).
- **Distractors.** A scored or validation item's other lessons are its repo's other lessons plus a seeded sample of every other repo's lessons, meta-train lessons included; none shares the lesson's failure key [established, `build_items`]. So the scored distractors include lessons the judge was trained to answer "yes" to, in their own situations.

## Training mix (fixed now)

The judge is a LoRA on Llama 3.2 1B (the CUDA trainer `train_lora_torch.py`, the round-2 lcap recipe, 1,024-token window), trained from plain weights with seeds 0, 1 and 2. Its rows come from `plug_r3_run.py bundle` (`plug_judge.judge_mix`):

1. **Judge rows under 15 phrasings.** The 618 meta-train items under their own situation and under each of V2's 14 phrasings (`plug_r2_rows.PHRASINGS`). Each phrasing gives 309 yes rows (the item's own lesson) and 309 no rows (balanced hard negatives from the ranker's top 10), so 4,635 yes and 4,635 no in all [measured].
2. **Habit replay.** The 202 AIDev habit rows (sha256 fa863cb3...), so the judge adapter keeps the habits (H3).

Total 9,472 rows, habit share 2.1% [measured]. 3 epochs at batch 4: `--iters 7104` [established, 9,472 x 3 / 4]. No other rows enter: this round makes no paid calls, and invented situations belong to the nightly track's own prereg.

## Decision procedure

1. **Validation fit (`plug_r3_run.py fit`).** On all 10 validation repos, each candidate's threshold is the lowest point of its fixed grid where silence is at least 0.80 and wrong pick at most 0.05 (points over the items). The judge's grid (`plug_judge_cli.GRID`) is P(yes) from 0.00 to 1.00 in steps of 0.01, plus 0.991 to 0.999. The thresholded ranker's grid is its top inverse-document-frequency score, 0 to 30 in steps of 0.25. Each seed alone also gets its own threshold. A candidate with no safe point is reported as "cannot be made safe". The thresholds, per-seed thresholds, validation rates, the ranker's top-score range and the MDE go into a dated amendment before any scored answer. If the judge has no safe point, there is no scored run and the amendment says so.
2. **Scored run (`plug_r3.sh scored`, then `plug_r3_score.py`).** Once, on the 40 scored repos, at those thresholds, from the code commit pinned at the freeze.

## Definitions

- **Pick:** on pick items, the chosen lesson is the applicable one. **Silence:** on silence items, nothing is chosen.
- **Wrong pick:** (answered minus right) over all items, pick and silence items together (`plug_judge.outcome_rates`).
- **Precision:** right over answered, pooled over the row's items; a row that answered nothing has none.
- **H1 statistic:** the mean over repos of per-repo pick (each repo weighs the same), paired by repo.
- **The judge** is the 3-seed ensemble (mean P(yes)) at its fitted threshold; every claim is about the ensemble.

## Rows and labels (scored repos)

| Row | Label |
|---|---|
| judge, 1B, seed mean of P(yes), fitted threshold | under test |
| ranker with its fitted threshold on its top score | reference (the primary comparison) |
| ranker alone, always answering its top lesson | reference |
| untrained 1B as judge, its own fitted threshold (or "cannot be made safe") | floor |
| plain 1B reading the top 5 (round 2's floor prompt) | floor |
| judge on the seen set (meta-train items under the unseen wording below) | reference (H4) |

## Hypotheses

- **H1 (primary).** Judge minus thresholded ranker, per-repo pick, paired over the 40 scored repos. Every applicable lesson in those items was added after the judge was frozen. Expected: `better` [hypothesis].
- **H2 (safety gate).** The judge's silence is at least 0.80 with the 95% interval's lower bound above 0.60, and its wrong pick is at most 0.05 with the upper bound at most 0.10 (per-repo rates, intervals over repos) [hypothesis].
- **H3 (habits gate).** The judge adapter keeps ranked-choice habits at 0.90 or more on the seed mean (`rank_habits_torch.py`, the 44 AIDev questions). The report prints the Wilson interval over 44 questions and the untrained 1B's score beside it [hypothesis].
- **H4 (new-lesson gate).** New lessons do about as well as seen ones: the judge's per-repo pick on the scored repos minus its per-repo pick on the seen set is at least -0.05, with the 95% interval's lower bound at least -0.10 (repos resampled within each group, 10,000 resamples, seed 0) [hypothesis]. The seen set is the 618 meta-train items under one wording that no training row uses, frozen as `plug_r3.SEEN_WORDING`: "Something broke. Repo: {repo}. Edited: {file}. Ran: `{failed}`. Saw: {error}". So the seen lessons are trained ones and the situations are not.

## Decision rule

- **H1** reads `better` if the 95% interval's lower bound is above 0 and the mean gain is at least 0.05, `worse` if the upper bound is below 0, and `tie` otherwise [established]. Intervals are percentile bootstrap intervals over repos (10,000 resamples, seed 0) [established].
- **No safe comparator.** If the thresholded ranker has no safe point on validation, H1 reads `no safe comparator`, never `better`, and the sentence says "the ranker could not be made silent at these limits". A gain over silence (pick 0) is never reported as a win.
- **The claim sentence is built in code (`plug_r3_decide.claim`) and always carries the ranker alone.** If H1 is `better` and H2, H3 and H4 pass: "on situations built from each lesson's own record, on 40 unseen repos, the judge's pick, precision, wrong pick X, P, W (ranker alone Y, Q, V); thresholded ranker picks T; silent in S with no applicable lesson". If H1 is `better` and a gate fails, the sentence names the failed gates. If H1 is `tie` or `worse`, it gives the gain and its interval. Every branch prints the judge's and the ranker alone's pick, precision and wrong pick.
- **Multiplicity.** One primary, conjunctive gates, descriptive secondaries: no correction; one decision.

## Secondary, never deciding

- **Judge minus the ranker alone,** pick and precision, paired by repo with intervals (precision over the repos where the judge answered at least once).
- **New failure keys:** pick and wrong pick on the scored lessons whose failure key never occurs in meta-train (`plug.lesson_key` against meta-train's keys; 160 of 165 lessons [measured]).
- **Wrong picks of trained lessons:** the share of the judge's wrong picks that chose a meta-train lesson.
- **Per seed:** each seed alone at its own validation threshold, with its H2; any seed that fails H2 is flagged.
- Precision versus coverage curves for every row.

## Minimum detectable effect

As in round 2: s is the per-repo standard deviation of the judge's validation pick gain over the thresholded ranker, scaled by √(8.3 / 4.1) for the scored repos' items per repo, and MDE = max(0.05, 1.96·s/√40) + 0.84·s/√40 [established]. s is measured in-sample on the fitting repos, so the MDE is optimistic. If it exceeds 0.10, the validation amendment says H1 is underpowered before any scored answer, and the round still runs as preregistered.

## Code the freeze must pin (all in commit 98ecc6b or later on `plug/round3`)

- `plug_judge.judge_mix` (rewordings and habit replay), with tests.
- The thresholded ranker (`plug_r3.ranker_choices`, `top_score_range`), with tests.
- The split checks (`plug_r3.check_splits`, `check_meta`), with tests.
- The runner: `plug_r3_run.py` (bundle, check with this prereg's name, fit and `selection.json`), `plug_r3_score.py` (the six rows, H1 to H4, secondaries and the claim), `plug_r3.sh` (CUDA training and scoring), and `plug_r3_decide.py` with tests for each claim branch (better, tie, worse, no safe comparator, a gate failure).
- The habits check of a judge adapter (`rank_habits_torch.py` on the 44 questions, in `plug_r3.sh scored`).

The freeze commit pins the code commit. No judge trained under this file answers anything before then.

## Known limits

- **The ranker alone picks more.** On exploratory numbers the always-answering ranker picks more than the judge (0.81 against 0.79 at an unsafe threshold) [measured]; the judge's case is precision and silence, and the claim prints both.
- **Post-hoc grids.** The exploratory grids were refined after the first ones were seen; the 0.991 to 0.999 points exist because of what was seen. The grids are fixed now.
- **No held-out check of the threshold.** The 5-versus-5 fit failed to transfer [measured], and fitting on all 10 removes the only held-out check, so H2 on the scored repos is the first transfer test.
- **Situations from the lesson's own record.** Situations are written from the lesson's own fields, which flatters the lexical ranker and the judge alike; the claim sentence says so.
- **Trained distractors.** Scored distractors include meta-train lessons the judge answered "yes" to in training; the wrong-pick share above measures how often that bites.
- One training recipe, three seeds; 40 small repos give coarse per-repo pick; habit rows are 2.1% of the mix [measured], so H3 may fail.
- The scorer is identity of the chosen lesson, so a verbatim note is exactly right or wrong.

## Not in this prereg

- **The nightly self-improvement work** (a3: invented situations, context distillation, base-answer replay, adapter scale) has its own exploratory track and prereg.
- **The downstream agent outcome** has its own preregs: phase 1, PLUG-AGENT-1 (`prereg/2026-10-29-plug-agent-outcome-DRAFT.md`, a small pilot on the validation repos' tasks), and phase 2, PLUG-AGENT-2 (about 150 tasks per arm [hypothesis]). No sentence of this round's claim implies agent success.

## Spend and machine

No paid spend in this round. Judge training and scoring run on the 5080 desktop (CUDA), executed by the CUDA-port agent from `plug_r3.sh`: 7,104 steps per seed, about 13 minutes each [hypothesis, from 463 steps in about 48 s measured]; scoring 1,660 validation, 3,300 scored and 6,180 seen queries per seed takes minutes [hypothesis].
