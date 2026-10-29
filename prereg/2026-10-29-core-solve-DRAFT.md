# DRAFT pre-registration: does Glimmer solve more new issues after learning from its own earlier work? (Core)

**DRAFT, not frozen.** The owner reviews this file. Freezing means committing a copy without "DRAFT" in its name, alone, before any scored run. After the freeze, only a dated amendment may change anything.

Claim tags: [measured] = observed in our own run; [established] = known by construction or from the literature; [hypothesis] = a guess this run can support or refute.

## Question and claim

Glimmer works on earlier issues in a repository. A Route B adapter is then trained on the runs that passed. Does that adapter make plain Glimmer solve more of the **later, held-out** issues of the same repositories?

- **Primary metric:** solve rate on the held-out tasks.
- **Diagnostic only:** mistake repeats and edit timing.
- **Wording:** the claim is "solves more new issues". There are no speed-of-learning claims.

## Test set (declared first: commit a380b5a, `results/core-test-set.json`)

45 tasks. Each carries its plain-Glimmer solve-rate estimate at cap 75 and the source of that estimate. [established]

| Repository | Tasks | Plain estimate [measured where given] |
|---|---|---|
| sqlglot | 20: the general split's 18 (10 bug, 8 feature) plus 3478 and 3339 | mean 0.38 over the 20. Sources: cap-75 plain runs for 8 tasks, cap-50 plain runs as a floor for the other 12 [measured] |
| Django | 25: SWE-Bench-CL `django_django_sequence` positions 25-49 (list at blob 00068409 on eval/swev-django) | unmeasured. All 25 are labeled "<15 min fix" by SWE-bench |

Rules for the test set:

- No run, gold patch or upstream fix of a test task may enter any training set.
- The collection manifest leaves out every test-task run and prints the count.
- The `sqlglot-all` adapter, the general and habits adapters and the old task-specific lessons all saw some of these tasks. They are never scored here [established].

## Earlier tasks and collection (unscored)

Model and settings: plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, reasoning low, **step cap 75**, wall cap 45 min, 2 runs per earlier task.

Earlier tasks:

- **sqlglot, 40 tasks:** the 9 that plain Glimmer ever solved, then the smallest dialects, expressions and parser tasks by date. None is a test task, and none has 2 or more plain cap-75 runs that all failed. [established]
- **Django, 24 tasks:** the SWE-Bench-CL history positions 1-24. [established]

What enters training:

- Only runs whose official evaluation resolves the task (FAIL_TO_PASS and PASS_TO_PASS pass).
- Earlier passing plain runs in the same mini-SWE-agent format are reused: 25 plain runs over 9 sqlglot tasks [measured].
- Lesson-arm and adapter-arm runs are listed but not used.

## Arms and labels

| Arm | Label | Notes |
|---|---|---|
| plain Glimmer | reference | 2 runs per test task |
| Glimmer + core adapter (trained on the collection manifest) | under test | 2 runs per test task; served under its own model name |

- The same step cap 75, wall cap 45 min and reasoning low apply to both arms. Both arms run in the same hours, with at most 4 concurrent requests.
- **No adapter that failed its install check is scored.** The install check is the Route B queue's `install ... ok` line, plus a plain-model check showing no LoRA on the plain child. A failed check means the arm is not run. If an arm has already run, it is reported as "not scored: failed install verification".
- A run that ends on an infrastructure or model_api error is rerun once. If it errors again, it counts as unsolved and is listed.

## Primary analysis

- **Statistic:** the paired per-task solve rate. For each task, take the mean of 2 runs per arm; then take the mean over tasks of (adapter minus plain).
- **Interval:** 95% bootstrap CI, resampling **tasks** with replacement 10,000 times, seed 20261029. [established]
- **Decision rule:** "Glimmer solves more new issues" is claimed only if the CI's lower bound is above 0. A CI that straddles 0 is reported as no detected difference. A CI wholly below 0 is reported as harm.
- **Reporting:** per repository and per kind (bug, feature), always beside the pooled number. Those breakdowns are descriptive, not tests.

## Secondary (descriptive)

- The step of the first source edit, as the paired per-task median difference. Runs with no edit count as the step cap.
- Submitted-but-wrong patches.
- Repeated identical commands per run.

## Known limits

- **Small n.** 45 tasks with 2 runs each. [hypothesis] Only a difference of about 15 points or more is likely to clear the CI.
- **sqlglot "later" is not strictly by date.** The 18 split tasks were chosen by plain record, not created after every collection task. Django is strictly later (CL order).
- **The sqlglot estimates mix caps.** 12 of 20 come from cap-50 runs, which are a floor at cap 75: CAL2 found tasks solved once at cap 50 mostly solve twice at cap 75 [measured]. The test set may be easier than the 0.38 estimate suggests.
- **Django has no plain Glimmer data yet.** The plain arm of this run is its first measurement.
- **The two repositories differ.** The training set will be dominated by whichever repository yields more passing runs.

## Cost [hypothesis]

- **Collection:** 80 sqlglot runs and 48 Django runs, 2 workers each, side by side, at about 15-20 min per run. That is about 10-11 h of wall time.
- **Scored evaluation:** 180 runs at 4 slots, about 12-14 h.
