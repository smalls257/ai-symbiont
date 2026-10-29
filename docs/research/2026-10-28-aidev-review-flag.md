# AIDev review-flag signal and general lessons (2026-10-28)

Source: AIDev v4 ([HF hao-li/AIDev](https://huggingface.co/datasets/hao-li/AIDev), revision tagged v4, CC-BY-4.0), by Hao Li et al., [arXiv 2507.15003](https://arxiv.org/abs/2507.15003). Tables used: `pull_request`, `repository`, `pr_commits`, `pr_commit_details`, `pr_reviews`, `pr_review_comments`. Patch text and comment bodies stay under each source repository's license. They are parsed locally and never redistributed: lessons, training rows and `results/aidev-lessons.json` hold only template prose, counts and labels. The run is exploratory: there is no prereg and nothing here is scored.

Code: `scripts/aidev/` (pure: `hunks.py`, `flags.py`, `order.py`, `lessons.py`, `training.py`, `report.py`, `score_habits.py`; periphery: `load.py`, `build.py`, `check_tokens.py`). Tests: `tests/scripts/test_aidev_flags.py`, `tests/scripts/test_aidev_lessons.py`. Outputs go to `~/symbiont-runs/aidev/` and are never committed.

## 1. Commit order

AIDev has no commit timestamps and no parent links, so "a later commit" can only mean "a later row of `pr_commits`". Three checks that need no text show that row order is chronological, oldest first [measured]:

| Check | Agree | Disagree |
|---|---|---|
| A file a commit adds is modified only by later rows | 61,478 | 214 |
| A comment's `commit_id` (PR head) is not an earlier row than its `original_commit_id` | 69,031 | 0 |
| Copilot's "Initial plan" commit is the first row of a multi-commit PR | 20,516 | 835 |

A sha listed twice for one PR keeps its first row.

## 2. Definition of the `review_flag` label

- **Unit.** One hunk of one commit that adds lines, keyed by file and its added line numbers.
- **Tracking.** The unit's line runs are carried through each later commit of the same PR. They shift when that commit's change to the file sits elsewhere. The unit is **changed** at the first commit that removes one of its lines, inserts inside a run, or deletes the file.
- **Flag.** A thread-opening inline review comment (`in_reply_to_id` null) anchors at the last line of its `diff_hunk`, on the new side, in the file at its `original_commit_id`. It flags the live unit whose runs hold that line at that commit. **Human** means `user_type = User` and a login without `[bot]`. **Bot** means everything else.
- **Outcome.** A flagged unit counts only commits after the flag; an unflagged unit counts commits after its own commit. A unit with no commit after that point is **censored**. A unit whose file a later commit changed with no readable patch, or that met a commit with no file rows, is **unknown**. Neither censored nor unknown units ever count as survived; both are left out of the rate and reported.
- **Two cuts.** `all` (as above) and `first_review`: units live at the PR's first human-commented commit, judged after it, which gives both arms the same window. In both cuts a unit flagged only by bots is its own arm, never unflagged.

Comments that do not anchor are counted [measured]: 31,410 anchored, 12,291 on a line the PR did not add, 6,778 on a commit no longer in the PR's list (force-pushed), 803 on the old side, 291 on a file whose tracking was lost.

## 3. The signal

Rate = changed / (changed + survived). The human-flagged row is under test; bot-flagged and unflagged rows are its reference [measured].

| Cut | Agent | Human-flagged | Bot-flagged | Unflagged | Lift (human / unflagged) |
|---|---|---|---|---|---|
| all | all agents | 0.905 (12,326 / 13,618) | 0.658 (3,987 / 6,064) | 0.193 (172,573 / 896,310) | 4.70 |
| all | Copilot | 0.922 (9,941 / 10,788) | 0.658 | 0.206 | 4.48 |
| all | Devin | 0.880 (1,481 / 1,684) | 0.694 | 0.174 | 5.06 |
| all | Cursor | 0.845 (272 / 322) | 0.644 | 0.204 | 4.14 |
| all | OpenAI Codex | 0.784 (399 / 509) | 0.671 | 0.146 | 5.37 |
| all | Claude Code | 0.705 (189 / 268) | 0.603 | 0.205 | 3.44 |
| all | Google Jules | 0.936 (44 / 47) | 0.833 | 0.203 | 4.61 |
| first_review | all agents | 0.893 (8,797 / 9,857) | 0.432 (227 / 525) | 0.152 (26,875 / 177,284) | 5.89 |

The owner's figure (about 90% flagged against about 23% unflagged) holds for flagged hunks. Our unflagged rate is lower, 19% or 15% depending on the cut [measured]. Copilot carries 79% of judged human flags [measured]. On Copilot PRs the reviewer's comment is also how the agent is asked for its next commit, so part of the lift may be the review loop rather than the mistake [hypothesis].

**The miner's own rule agrees.** `symbiont.miner.signals.review_flag` judges by content: a later edit removes a line the review hunk added. Applied to the same human-flagged units, it says "changed" for 11,589 of the 12,326 that line tracking calls changed, and for 80 of the 1,292 it calls survived: 94% agreement overall [measured].

## 4. Use by the miner or warner

`~/symbiont-runs/aidev/review_flag_labels.jsonl` holds one row per unit: `pr_id`, `agent`, `path`, `commit_index`, `added_lines`, `flag` (`human`, `bot`, `none`), `flagged_at`, `outcome` (`changed`, `survived`, `censored`, `unknown`). As a **label** it says a reviewer's flag on a hunk predicted rework in that PR. As a **feature prior** for the warner, P(changed | human flag) and P(changed | unflagged) per agent are in `results/aidev-lessons.json` (`rows`, `lift_human_over_unflagged`). The miner's live `review_flag` signal is unchanged; its content rule is the one checked above.

## 5. Lessons with resolutions

A human-flagged unit becomes a lesson only if all of these hold: the repository's language is Python, the file is `.py`, the comment matches one of five rule-based kinds (`scripts/aidev/lessons.py`, first match wins), and a later commit resolved it. A resolution is the commit that reworked the unit's lines; for `tests_missing`, a later change to a test file also counts. Each lesson is three template sentences: what happened (function and file), how it was resolved (line counts, tests touched) and the check to run. No reviewer or patch text is used.

| Kind | Lessons |
|---|---|
| error_handling | 35 |
| tests_missing | 16 |
| naming_convention | 16 |
| wrong_module | 15 |
| api_misuse | 12 |
| **total** | **94, from 38 repositories** |

Kinds come from keyword rules; their precision has not been checked by reading comments [hypothesis].

All counts in this section are [measured]. Dropped, by reason: 13,729 human flags not in a Python repo or not on a `.py` file, 945 of no general kind, and 22 not resolved. Python is a small part of AIDev's reviewed PRs: 3,876 human thread-opening comments in Python repositories. The rules match on keywords only; their precision has not been checked by reading comments [hypothesis].

## 6. Route B habits set

`~/symbiont-runs/aidev/routeb/`: mlx-lm chat rows (system, user, assistant), with self-study Q&A (what happened and how it was resolved; recall of the lesson) and situation-to-corrected-action pairs. Whole repositories are held out (`training.assign_splits`, stable hash order, at least 20% of lessons held out and 5% for validation); the split is in `split.json` [measured]:

| Split | Repositories | Lessons | Rows |
|---|---|---|---|
| train | 26 | 67 | 202 |
| valid | 4 | 5 | 18 |
| held out | 8 | 22 | 70 rows, 44 reworded questions |

The longest row is 206 tokens under the Llama 3.2 chat template and 186 under Qwen 2.5, both under the 512-token training window (`check_tokens.py`) [measured]. Glimmer's own template was not checked on the laptop [hypothesis that it fits].

## 7. Habits adapter, first look (exploratory)

A Llama 3.2 1B Instruct LoRA was trained on the laptop with MLX, using the shared LCAP recipe (`scripts/routea/train_lora.sh`, 8 epochs, rank 16, 404 iterations) on the 202 train rows, in 317 s with a 6.5 GB peak [measured]. It then answered the 44 held-out questions [measured], which come from repositories it never saw and use wordings and situations not in training, through `scripts/routea/answer_questions.py`. `score_habits.py` scores an answer as a hit when it names the key term of its lesson's check, and as off-kind when it names only another kind's term.

| Arm | Role | Hit | Off-kind | Miss | Hit rate |
|---|---|---|---|---|---|
| base model, same system prompt | floor | 22 | 18 | 4 | 0.50 |
| habits adapter | under test | 28 | 16 | 0 | 0.64 |

**Correction (2026-10-28).** The first version of this table gave the base model 4 hits (0.09). That run used the old `answer_questions.py`, which kept only an answer's first line. Base Llama puts its checklist after a newline, so most of its answer was cut. Since ef0954a the answerer keeps the whole answer, and every row above uses that version; the habits adapter's answers are one line either way and score the same [measured]. The adapter's lead over the floor is therefore 6 hits, not 24 [measured]. A longer answer can also mention a kind's key term by chance, so this scorer separates arms weakly [hypothesis].

All rows are [measured]. Error-handling questions account for all 16 off-kind answers (10 of 26 hit). The held-out set covers four kinds, eight repositories and one situation wording per kind, so the adapter may have learned to map each situation to its check rather than a habit that transfers [hypothesis].
