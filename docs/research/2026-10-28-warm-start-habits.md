# Learning to learn for the MCP route: warm start, and Plug feasibility (2026-10-28)

Exploratory; no prereg. Everything ran on the laptop with MLX on Llama 3.2 1B Instruct. Lessons are LCAP lessons (one failed command, its error and the command that fixed it) from the public nebius OpenHands trajectories (CC-BY-4.0). The habits adapter and habit questions come from AIDev (`docs/research/2026-10-28-aidev-review-flag.md`). Results: `results/warm-start-habits.json`, `results/l2l-quick.json`, `results/l2l-a3.json`. Code: `scripts/routea/{warm_start,l2l_quick,plug,rank_habits}.py` and the `warm_start.sh`, `l2l_quick.sh` and `l2l_a3.sh` drivers. Tests: `tests/scripts/test_{warm_start,plug}.py`.

## One answer script for every row

`scripts/routea/answer_questions.py` changed in `ef0954a` from "keep the first line" to "keep the whole answer, folded onto one line". The warm-start run started before this branch picked that change up, so its first pass mixed both versions [measured]. Every cell was answered again from its trained adapter with the current script, and only those answers are scored here. The first-pass answers are kept apart and never pooled with them. The same change corrects the AIDev habits table (section 7 of the AIDev note).

## 1. Warm start: does the habits adapter help a new repo's lessons?

The claim under test: with the AIDev habits adapter as the starting point, a per-repo LoRA learns a new repo's lessons from fewer of them than from plain 1B. Fifteen repos have 10 or more distinct lessons; T46's scored repos and sqlglot are excluded, and none of the 15 is an AIDev repo [measured]. Each repo trains at 5 and 10 nested lessons, plus 20 for the one repo that has them. Both starts use the same rows and the LCAP recipe (8 epochs, rank 16). Recall is the LCAP scorer on the repo's reworded probes (templates unseen in training) and on the verbatim training questions. Gains are paired by repo, with a 95% bootstrap over repos (10,000 resamples, seed 0).

| Lessons | Plain start (reference): reworded / verbatim | Habits start (under test): reworded / verbatim | Habits minus plain, reworded, with interval |
|---|---|---|---|
| 5 (15 repos) [measured] | 0.603 / 0.780 | 0.528 / 0.753 | −0.075 [−0.139, −0.008] |
| 10 (15 repos) [measured] | 0.575 / 0.737 | 0.497 / 0.731 | −0.077 [−0.120, −0.035] |
| 20 (1 repo) [measured] | 0.370 / 0.575 | 0.430 / 0.650 | one repo, no interval |

All rows are [measured]. The habits start learns a new repo's lessons slightly *worse*, not from fewer of them, so the claim fails on this data.

Whether habits survive per-repo training depends on the check, and the two checks disagree:
- **Ranked choice (primary).** At 5 lessons the habits start keeps 0.64 against 0.21 for the plain start (+0.43 [+0.28, +0.57], 15 repos) [measured]. The habits adapter alone scores 0.70 [measured], so most habits survive 5 lessons of training. Budget 10 was not ranked for the warm-start adapters. Arm b at 10 lessons fell to 0.27 [measured], so forgetting may grow with training steps [hypothesis].
- **Keyword score.** It said the opposite, 0.19 against 0.29 (−0.10 [−0.15, −0.05]) [measured]. It is the weaker check (section 3).

## 2. Plug feasibility on one repo (Azure/msrest-for-python, control CORE-GATECH-GROUP/serpent-tools)

Goal: an unseen repo improves after a few lessons, with no tuning per user. Five arms; numbers are at 5 / 10 lessons; "wrong" means the control repo's lessons in place of the repo's own.

| Arm | Reworded recall | Habits kept: keyword (ranked) | Wrong-lesson recall |
|---|---|---|---|
| Per-repo adapter from plain 1B (reference) | 0.64 / 0.48 | 0.18 / 0.25 | 0 / 0 |
| Per-repo adapter from habits adapter | 0.36 / 0.48 | 0.23 / 0.14 | 0 / 0 |
| b: fresh adapter over the frozen habits adapter | 0.36 / 0.48 | 0.25 / 0.11 (0.86 / 0.27) | 0 / 0 |
| a1: plain 1B, lessons in the prompt | 0.28 / 0.28 | 0.50 (0.20) | 0 / 0 |
| a1 with the habits adapter | 0.00 / 0.00 | 0.64 (0.70) | 0 / 0 |
| a2: meta-trained once on other repos, lessons in the prompt | 0.60 / 0.48 | 0.41 (0.80) | 0 / 0 |
| a3: a2 plus a per-repo adapter, reading rows mixed in | 0.40 / 0.50 | 0.41 (0.27) | 0 / 0 |

All rows are [measured], one repo, 25 reworded probes per lesson budget. The decisions and other details:
- **b (killed).** b fuses the habits adapter into a copy of the base model and trains a fresh adapter on top, which is the same function as stacking over a frozen adapter. The kill rested on the keyword habits score falling below the 50% bar [measured]. On ranked choice b keeps habits at 5 lessons (0.86) and loses them at 10 (0.27) [measured]. Its recall (0.36 at 5) stays below the plain per-repo adapter's either way, so it still does not go.
- **a2 (passes the feasibility rule).** It was meta-trained on 1,546 rows: lessons in the prompt with the answer, abstain rows, and the AIDev habit rows. It nearly matches a per-repo adapter with no training for the repo, and with its lessons removed it recalls nothing [measured].
- **a3 (hold).** With its lessons removed from the prompt it recalls 0.40 / 0.44, below the per-repo adapter, so it does not go. New lessons in the prompt score 0.33 / 0.40, above a1's 0.27, so it is not killed. Its ranked habits fall to 0.27 [measured].
- **Wrong-lesson recall** is 0 for every arm, so it separates nothing. The scored prereg replaces it with a confabulation rate.

## 3. A better habits check

The keyword score marks a hit when an answer names its kind's key term anywhere, so a long checklist scores by chance: plain 1B gets 0.50 on it [measured]. The ranked-choice check (`rank_habits.py`) scores the five kinds' check sentences by mean log-likelihood per reply token, with no generation. Plain 1B gets 9/44, at chance (0.20), the habits adapter 31/44 and the feasibility a2 35/44 [measured]. The scored Plug run uses it as primary.

## Next

The scored Plug run is `prereg/2026-10-28-l2l-a2-DRAFT.md`: 13 unseen repos, a2 trained again with those repos held out by check, a1 as the plug-and-play baseline, and a confabulation control. The feasibility a2 saw those repos, so it is discarded [measured]. These results are one recipe on 1B and one seed per arm [hypothesis that seeds matter less than repo spread].
