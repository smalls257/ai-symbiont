# Pre-registration: Plug round 3, a pairwise judge over the ranker's shortlist (PLUG-JUDGE)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before the judge trained under it answers any validation or scored item. After the freeze only a dated amendment may change anything, and an amendment cannot change the data, split, training mix, scorers, metric or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

Round 2 (`prereg/2026-10-29-plug-sit-cuda.md`) closed on validation with no scored run (`docs/research/2026-10-29-plug-round2-close.md`); it stays reported as it is. This round's design follows the exploratory round 3 (`docs/research/2026-10-29-plug-round3-exploratory.md`, `results/plug-r3-exploratory.json`).

## Amendments

(none at freeze)

## Question

A coding agent is in a situation: a command, a file and an error. A lexical ranker shortlists the 10 stored lessons that best match it. A judge, Llama 3.2 1B fine-tuned for one yes-or-no question, scores each shortlisted lesson: does it apply? If the top score clears a threshold fitted on validation repos, the agent receives that lesson's stored note, verbatim; otherwise it receives nothing. Does the judge pick the applicable lesson more often than the ranker with its own fitted threshold, on 40 repos neither has seen, while staying within the safety limits? The judge never writes a lesson, so it cannot invent one. No speed-of-learning words.

## What the exploration already saw (validation repos only)

- **Ranker coverage.** The ranker's top 10 hold the applicable lesson for every validation situation [measured].
- **Judge 1B.** At a threshold fitted on 5 validation repos, it picks 0.786 of situations on the other 5 with precision 0.767. Its wrong pick there is 0.119, over the 0.05 limit, so the fitted threshold did not transfer [measured]. Across all 10 repos, its best point within the limits picks 0.47 [measured]. 3B was worse [measured].
- **The ranker alone** answers everything: pick 0.81, silence 0 [measured].
- **V2 cannot be made safe.** Round 2's V2 reader, thresholded on its own confidence, cannot be made safe [measured], so it is not a reference here.
- **Post-hoc grids.** The exploratory threshold grids were refined after the first ones were seen; the grids below are fixed now.

## Data and split

- **Lessons, pins and plan.** As in round 2 (`plug_round2.py`, `plug_r2_score.PINNED`; pool index sha256 a14f22f0...).
- **Scored repos.** The 40 scored repos of round 2's plan (165 lessons [measured]), named in `prereg/2026-10-29-plug-sit-cuda.md`. No answer on them exists, because round 2 stopped before its scored run [measured]. `check_plan` refuses any other plan.
- **Validation repos.** The 10 repos of the a3 rerun, with 166 items in total [measured]. The threshold is fitted on all 10, the fix the exploration's transfer failure calls for.
- **Meta-training repos.** The 60 others [measured]. `plug.check_unseen` raises on any repo or lesson id shared with the validation or scored repos, so every scored lesson is added after training: the judge is tested on lessons it never saw.

## Training mix (fixed now)

The judge is a LoRA on Llama 3.2 1B (the CUDA trainer `train_lora_torch.py`, the round-2 recipe, 3 epochs), trained from plain weights with seeds 0, 1 and 2. Its rows (`plug_judge.judge_rows`, extended for this round) are:

1. **Judge rows.** Balanced, as in the exploration: each meta-train situation with its own lesson ("yes"), and as many hard negatives, the ranker's top-10 wrong lessons, answered "no".
2. **Rewordings.** The same judge rows again under V2's 14 situation phrasings (`plug_r2_rows.PHRASINGS`), kept balanced.
3. **Habit replay.** The 202 AIDev habit rows (sha256 fa863cb3...), so the judge adapter keeps the habits (H3).
4. **Invented situations.** Spark-written situations enter only through a dated amendment committed before training, with their count, cost and sha256. This workstream makes no paid calls.

## Decision procedure

1. **Validation fit.** On all 10 validation repos, each candidate's threshold is the lowest point of its fixed grid where silence is at least 0.80 and wrong pick at most 0.05. The judge's grid is P(yes) from 0.00 to 1.00 in steps of 0.01, plus 0.991 to 0.999. The thresholded ranker's grid is its top inverse-document-frequency score, from 0 to 30 in steps of 0.25. A candidate with no safe point is reported as "cannot be made safe" and does not enter the scored run. The thresholds and the validation numbers go into a dated amendment before any scored answer.
2. **Scored run.** Once, on the 40 scored repos, at those thresholds, from the code commit pinned at the freeze (`plug_r2_score.py check` refuses any other).

## Rows and labels (scored repos)

| Row | Label |
|---|---|
| judge, 1B, seed mean of P(yes), fitted threshold | under test |
| ranker with its fitted threshold on its top score | reference (the primary comparison) |
| ranker alone, always answering its top lesson | reference |
| untrained 1B as judge, its own fitted threshold (or "cannot be made safe") | floor |
| plain 1B reading the top 5 (round 2's floor prompt) | floor |

## Hypotheses

- **H1 (primary).** Judge minus thresholded ranker, pick, paired by repo over the 40 scored repos. Expected: `better` [hypothesis].
- **H2 (safety gate).** The judge's silence is at least 0.80 with the interval's lower bound above 0.60, and its wrong pick is at most 0.05.
- **H3 (habits gate).** The judge adapter keeps ranked-choice habits at 0.90 or more (`rank_habits_torch.py`, the 44 AIDev questions, seed mean) [hypothesis].

## Decision rule

- **H1** reads `better` if the 95% interval's lower bound is above 0 and the mean gain is at least 0.05, `worse` if the upper bound is below 0, and `tie` otherwise [established]. Intervals are percentile bootstrap intervals over repos (10,000 resamples, seed 0) [established].
- **The claim** "the judge picks the applicable lesson in X of situations on 40 unseen repos, against Y for the thresholded ranker, staying silent in Z of situations with none" is made only if H1 is `better`, H2 passes and H3 passes. Otherwise the sentence names what failed. The sentence is built in code.
- **Secondary, never deciding:** precision versus coverage curves for every row; the judge against the always-answering ranker at matched coverage; and the per-seed spread.

## Minimum detectable effect

As in round 2: s is the per-repo standard deviation of the judge's validation pick gain over the thresholded ranker, scaled by √(8.3 / 4.1) for the scored repos' item counts, and MDE = max(0.05, 1.96·s/√40) + 0.84·s/√40 [established]. The value goes into the validation amendment before any scored answer.

## Not in this prereg

- **The nightly self-improvement work** (a3: invented situations, context distillation, base-answer replay, adapter scale) has its own exploratory track and prereg.
- **The downstream agent outcome** against a basic retrieval floor is sized separately. It needs Glimmer or Spark and the SWE-rebench task images, and never decides this round. Sizing: about 150 tasks per arm [hypothesis].

## Code the freeze must pin (built before the freeze, as in round 2)

- `plug_judge.judge_rows` with the rewordings and habit replay above, with tests.
- The thresholded ranker: a top-score threshold on `lexical_rank`'s score, with tests.
- The round-3 runner: validation fit, the amendment's `selection.json`, the scored stage with the five rows, H1 to H3 and the claim sentence built in code, behind `plug_r2_score.py check` with this prereg's name.
- The habits check of a judge adapter (`rank_habits_torch.py` on the 44 questions).

The freeze commit pins the code commit that contains all four. No judge trained under this file answers anything before then.

## Known limits

- One training recipe, three seeds; 40 small repos give coarse per-repo pick.
- The threshold rests on 166 validation items from 10 repos, and the exploration showed a 5-repo fit did not transfer [measured].
- The lexical ranker is tuned to situations that quote the lesson's own fields.
- The scorer is identity of the chosen lesson, so a verbatim note is exactly right or wrong.

## Spend and machine

No paid spend in this workstream. Judge training and scoring run on the 5080 desktop (CUDA), executed by the CUDA-port agent: about 50 s per seed for 1B training and seconds per scoring pass [measured, exploratory]. The 3B judge is not in this round (worse in exploration [measured]).
