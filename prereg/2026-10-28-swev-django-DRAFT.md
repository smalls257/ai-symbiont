# Pre-registration DRAFT: plain vs personal Glimmer on SWE-bench Verified, Django, in date order

**Status: DRAFT, not frozen.** The controller freezes it after review by adding the freeze marker
in this header, in a commit that changes only the header. No phase-2 run starts before the freeze.

Claim tags: [measured] = observed in our own run, [established] = known from the benchmark's
documentation or the code's own documented behavior, [hypothesis] = a guess the run can support
or refute.

## Question

Does a personal Glimmer (the same Q4 Glimmer base plus a Django-only LoRA trained on lessons
mined from plain Glimmer's own earlier Django runs) resolve more of the later Django tasks of
SWE-bench Verified than plain Glimmer does? The claim is the paired difference between the two
arms on the same tasks. It is not a leaderboard number.

## Tasks and split (fixed by code, `scripts/swev/swev_tasks.py`)

- Source: the official `SWE-bench/SWE-bench_Verified` dataset, repo `django/django`, which has
  231 tasks. [measured]
- Kept: SWE-bench difficulty labels "<15 min fix" and "15 min - 1 hour". Dropped: "1-4 hours"
  and ">4 hours", because both arms are expected to fail them at a 50-step cap, and a task both
  arms fail adds no information to a paired difference. [hypothesis]
- Excluded by measurement: tasks whose official FAIL_TO_PASS tests already pass on the
  untouched base tree, because any patch would "resolve" them. So far this is `django__django-7530`.
  [measured] (`validate_scorer.py`) Before launch, every picked task gets the same no-patch check.
  Any new exclusion is added to `EXCLUDED` and the list is rebuilt by the same rule before the freeze.
- Order: `created_at`, with ties broken by instance id. Phase 1 ("history") is the earliest 20 kept
  tasks. Phase 2 ("later", scored) is the next 20. Ids, dates and labels are in
  `results/swev-django-tasks.json`.
- Hold-out: lessons come only from phase-1 runs. `select_lessons.py` raises
  `HoldOutViolationError` for a lesson whose source task is not in phase 1. It drops, and names,
  any lesson that quotes a distinctive line (20 or more characters, containing a letter) of a
  phase-2 gold patch.

## Arms (row labels)

| Arm | Label | What runs |
|---|---|---|
| plain | floor | Muse-Glimmer-30B Q4_K_M, the calibration's endpoint |
| personal | under test | the same base plus the Django-only LoRA trained on phase-1 lessons |

No notes are injected into either arm's prompt: the adapter is the only difference. Both arms use
the same harness: mini-SWE-agent 2.4.6 with its `swebench.yaml` config (bash only), the
"Reasoning strength: low" line, the same step cap (50 unless the pilot rule below raises it), a
30-minute wall cap, no network for the agent, and each task's own official image with refs past
HEAD removed.

## Grading

Grading uses the official hidden tests. Each run is graded in a fresh container from the task's
official image with the row's own `eval_script` (it applies the hidden test patch and runs
FAIL_TO_PASS and PASS_TO_PASS), the official patch-apply order and the official `get_eval_report`.
A run counts as resolved only on the official FULL status. A run whose test output cannot be
parsed is ungraded and retried, up to 3 attempts. It is never counted as a pass or a fail.
[established] (swebench 5.0.2) The scorer was validated on the pilot tasks: the gold patch
resolves and no patch does not; see `swev-report.md`. [measured]

## Pilot and step cap (before phase 1)

The pilot uses 3 pilot tasks (the first 3 phase-1 tasks), plain arm, 1 run each, at a 75-step cap. [established] (by construction)
Rule: if 2 or more of the 3 pilot runs use more than 50 steps before they submit, the cap for
both phases is 75. Otherwise it is 50. The pilot runs are history-side tasks, so they never touch
phase 2.

## Metrics

- **Primary:** the paired difference in resolved rate on phase 2, personal minus plain. Each arm
  has 2 runs per task, and a task's score is its mean over those runs. [established] (by construction)
  The 95% CI is a task-level bootstrap: 10,000 resamples of the 20 tasks, seed 20261028. [established] (by construction)
- **Secondary:** repeated-mistake counts per run (the same failing command run twice or more, and
  the same file reworked three or more times, both counted by the miner on main), and the steps
  used per run. Each is reported as a paired difference with the same bootstrap.
- The plain row is always printed beside the personal row.

## Decision words

- "Personal Glimmer helps on later Django tasks" only if the primary CI lies entirely above 0.
- "Personal Glimmer hurts" only if the CI lies entirely below 0.
- Otherwise "no detectable difference at this sample size", with the CI printed.
- A secondary metric never upgrades the primary verdict.

## Known limits

- Contamination: Glimmer may have seen SWE-bench Verified or the Django fixes in pretraining.
  That affects both arms equally, so only the paired difference is claimed. [hypothesis]
- Small n: 20 scored tasks with 2 runs per arm. The smallest difference this can detect is large,
  roughly 15 to 20 points of resolved rate. [hypothesis]
- The base is a Q4_K_M quantization and the LoRA is trained on the bf16 weights. The adapter is
  served on the quantized base.
- The harness is not Meta's: mini-SWE-agent with bash only, so resolved rates are not comparable
  to published Glimmer numbers.
- The difficulty filter and the exclusions make the task set easier than Verified as a whole.
- History is Glimmer's own 20 runs, one per task, so the lesson count is small and depends on how
  often plain Glimmer makes a repeated mistake.

## Spend

None. Local Glimmer, the desktop's docker, and the Strix GPU for training. [established]
