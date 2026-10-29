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

## Order of work (owner redirect 2026-10-29)

1. **Measure the plain spread first.** Plain Glimmer runs 2 times on about 30 earlier tasks (about 60 runs, collection below). The per-task disagreement rate (tasks whose two runs differ) gives v for the MDE [established].
2. **Compute the MDE before any scored run,** from that spread (`scripts/routeb/core_mde.py`), and record it in an amendment. The runs per arm are then fixed: 4 or more [established].
3. **Train the adapters,** then run the scored arms.

## Earlier tasks (unscored): plain collection and teacher runs

The earlier tasks:

- **sqlglot, 40 tasks:** the 9 that plain Glimmer ever solved, then the smallest dialects, expressions and parser tasks by date. None is a test task, and none has 2 or more plain cap-75 runs that all failed. [established]
- **Django, 24 tasks:** the SWE-Bench-CL history positions 1-24. [established]

**Plain collection.** Plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, reasoning low, step cap 75, wall cap 45 min, 2 runs per task. It stops once about 30 tasks have 2 runs. Its main use is measuring the spread. Self-training on Glimmer's own passes is expected to give only 0 to +3 points (SWE-Gym, 32B: 19.0 to 19.7) [established], which is below this design's MDE.

**Teacher runs (the main lever).** The teacher is Muse Spark (Contributor tier). Muse Wonder is out of budget at its unconfirmed standard price [hypothesis].

**Budget.** The ledger enforces a total cap of $60 over all workstreams (owner, 2026-10-29) [established].

- The aim is 1-2 passing runs per earlier task, harder tasks first (lowest plain solve rate).
- The per-run cap is $0.15, raised to $0.25 only for a task whose run hit the cap once. [established]
- Runs stop when the ledger would pass the cap.
- A cap-aborted run is recorded with its reason and is never kept for training.

- It solves the earlier tasks in mini-SWE-agent format, through `symbiont.egress`, with the spend ledger and its caps.
- The driver refuses any test-set task before its first call.
- Published teacher-trajectory gains are +13 to +27 points [established].

**What enters training.**

- Only runs whose official evaluation resolves the task (FAIL_TO_PASS and PASS_TO_PASS pass).
- 1-2 kept passing runs per earlier task.
- Each row is tagged with its source (Glimmer or teacher) and model, and the mix is reported.

## Arms and labels

| Arm | Label | Notes |
|---|---|---|
| plain Glimmer | reference | 4 or more runs per test task (fixed by the MDE amendment) |
| Glimmer + Core adapter (teacher and own passing runs on the earlier tasks of these repositories) | under test | same runs per task; served under its own model name |
| Glimmer + control adapter (same recipe and row count, trained on passing runs from OTHER repositories) | control | same runs per task; separates "learned this repository" from "learned to act like an agent" |

| Glimmer + worked examples in the prompt (fallback, own arm) | under test | for each test task, the teacher's passing trajectories of the most similar EARLIER tasks, retrieved by similarity of issue text, are put in the prompt as worked examples; same test tasks, same runs per task, paired with plain |

The **worked-examples arm** is pre-registered as the fallback in case the Core adapter ties plain.

- Retrieval uses only earlier-task teacher solves. It never draws on a test task's run or fix.
- The number of examples and the word budget are fixed before scoring: about 2 examples, each cut to its edit and test commands [hypothesis].
- The arm is scored with the same statistic as the adapter (worked examples minus plain). It is reported beside the adapter, never instead of it.

Rules for every arm:

- **Same settings.** Every arm uses step cap 75, wall cap 45 min and reasoning low. All arms run in the same hours, with at most 4 concurrent requests.
- **No adapter that failed its install check is scored.** The install check is the Route B queue's `install ... ok` line, plus a plain-model check showing no LoRA on the plain child. A failed check means the arm is not run. If an arm has already run, it is reported as "not scored: failed install verification".
- **Infra errors are not failures.** A run that ends on an infrastructure or model_api error, or because Glimmer was stopped, is void and re-queued; it is never scored as a failure. A run that errors twice is listed.

## Primary analysis

- **Statistic:** the paired per-task solve rate, compared task by task. For each task, take the mean of its runs per arm; then take the mean over tasks of (Core adapter minus plain). The same statistic for (Core minus control) is the second test.
- **Interval:** 95% bootstrap CI, resampling **tasks** with replacement 10,000 times, seed 20261029. [established]
- **Decision rule:** "Glimmer solves more new issues" is claimed only if the CI's lower bound is above 0. A CI that straddles 0 is reported as no detected difference. A CI wholly below 0 is reported as harm.
- **Reporting:** per repository and per kind (bug, feature), always beside the pooled number. Those breakdowns are descriptive, not tests.

## Secondary (descriptive)

- **Empty patches:** runs that submit nothing or end with an empty diff, per arm.
- **Loops:** repeated identical commands per run, and runs with any command repeated 5 or more times.
- **Turns:** steps used per run, and the step of the first source edit (paired per-task median difference; a run with no edit counts as the step cap).
- **Wrong submissions:** patches submitted but not resolving the task.

## Minimum detectable effect (alpha 0.05, power 0.8, paired by task)

Computed by `scripts/routeb/core_mde.py` from the plain runs we have.

Model:

- Per task, (adapter mean minus plain mean) over r runs per arm has variance 2v/r, where v is the mean over tasks of p(1-p) [established].
- MDE = (1.96 + 0.84) x sqrt(2v / (r x n)), with n = 45 [established].
- This assumes the adapter shifts every task's rate equally. Real heterogeneity would make the MDE larger [hypothesis].

Source of v (all [measured]):

| Source of v | v | Tasks | MDE, 2 runs/arm | MDE, 4 runs/arm | Runs per arm for 5 points | Runs per arm for 10 points |
|---|---|---|---|---|---|---|
| plain run 1 vs run 2, 18 split tasks (unselected) | 0.056 | 18 | 9.8 points | 7.0 | 8 | 2 |
| plain repeats at cap 50, test-set sqlglot tasks | 0.126 | 18 | 14.8 | 10.5 | 18 | 5 |
| plain repeats at cap 75, test-set sqlglot tasks | 0.188 | 8 | 18.1 | 12.8 | 27 | 7 |

How to read the sources:

- The repeat rows come from tasks that were picked because they had solved once, so they overstate v [hypothesis].
- The unselected run-1-versus-run-2 row is the best guess. **With 2 runs per arm, the design detects about 10-15 points, not 5.**
- No Django plain data exists yet, so Django is assumed to vary like sqlglot [hypothesis].

**What 5 points would cost.** It needs 8-27 runs per arm per task, which is 720-2,430 runs over 45 tasks [measured from the table]. Measured Glimmer throughput at 4 slots was 4.8-5.7 min of wall time per run at cap 50 (pilot and overnight) [measured]. Cap 75 assumed about 6-7 min [hypothesis]. That makes 72-280 Glimmer hours, which is not feasible here [hypothesis].

**Proposal.** 4 runs per arm on the 45 tasks: 360 runs, about 36-42 Glimmer hours, MDE about 7-13 points. The fallback is the planned 2 runs per arm: 180 runs, about 18-21 h, MDE about 10-18 points. In either case the decision rule stays the task-bootstrap CI, and the claim is reported with its MDE beside it [hypothesis].

## Known limits

- **Small n.** 45 tasks with 2 runs each detect about 10-15 points (MDE above) [measured].
- **sqlglot "later" is not strictly by date.** The 18 split tasks were chosen by plain record, not created after every collection task. Django is strictly later (CL order).
- **The sqlglot estimates mix caps.** 12 of 20 come from cap-50 runs, which are a floor at cap 75: CAL2 found tasks solved once at cap 50 mostly solve twice at cap 75 [measured]. The test set may be easier than the 0.38 estimate suggests.
- **Django has no plain Glimmer data yet.** The plain arm of this run is its first measurement.
- **The two repositories differ.** The training set will be dominated by whichever repository yields more passing runs.

## Cost [hypothesis]

- **Collection:** 80 sqlglot runs and 48 Django runs, 2 workers each, side by side, at about 15-20 min per run. That is about 10-11 h of wall time.
- **Scored evaluation:** 180 runs at 4 slots, about 18-21 h at the measured 4.8-5.7 min per run, or 36-42 h at 4 runs per arm.
