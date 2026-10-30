# DRAFT pre-registration: Core D2, does Glimmer solve more later issues of a repository after training on solved earlier ones?

**DRAFT, NOT FROZEN** (revision 4: the Opus proxy's 11 fix-first items, the temperature result, the hash-order test set, the re-check's text fixes and the built runner). The freeze is a copy without "DRAFT" in its name, committed alone before any adapter result exists. After the freeze, only a dated amendment may change anything, and an amendment cannot change the tasks, arms, measures or decision rule. This supersedes `2026-10-29-core-solve-DRAFT.md`.

Claim tags: [measured] = observed in our own run; [established] = known by construction or from the literature; [hypothesis] = a guess this run can support or refute.

## Claim (headline wording fixed now)

"Glimmer solves more of a repository's later issues after training on past sessions of the same repository."

- The claim needs BOTH co-primaries below.
- No speed-of-learning words are used.

## Repositories, earlier and later tasks [established]

There are six repositories:

- `tobymao/sqlglot`
- `django/django`
- `streamlink/streamlink`
- `conan-io/conan`
- `iterative/dvc`
- `PennyLaneAI/pennylane`

Tasks are SWE-rebench instances with images (SWE-bench Verified for Django).

**Earlier tasks.** These are the only training sources.

| Repository | Earlier tasks |
|---|---|
| New repositories | the first 55% of tasks by creation date [established] |
| sqlglot | the first 55% by creation date (161 tasks); the existing teacher passes count only if their task is among them [established] |
| Django | SWE-Bench-CL positions 1-24 |

**Later candidates.** A later task stays a candidate only if all of these hold (`split-check.json`):

1. **Commit order.** Its base commit is strictly later, by git commit date, than every earlier task's base commit in the same repository.
2. **Fix-area match.** Its gold patch changes a source file that some earlier task also changed.
3. **No duplicate or revert.** At least half of its added lines must not duplicate an earlier task's added or removed lines.

Candidates after these rules:

| Repository | Candidates | Dropped |
|---|---|---|
| streamlink | 9 | none |
| conan | 18 | none |
| dvc | 15 | 1 on commit date |
| pennylane | 31 | none |
| sqlglot | 107 | none; the 20 tasks of the former test set are excluded outright, since results on them were already seen [established] |
| Django | 54 | 1 duplicate (CL 25-49 plus 30 scorer-checked Verified tasks, "15 min - 1 hour") |

That is 234 candidates in all.

**Training refusal.** The training manifest refuses any run on ANY of the 234 later candidates, not only on test tasks, and reports how many it refused [established, by construction].

## Test-set selection (set before any adapter result)

**Screening is not used.** Plain Glimmer's own outcomes play no part in choosing tasks. A screening run was started and stopped on the owner's order after 10 graded runs; those runs never count and never select [established].

The test tasks are the first 100 of the 234 later candidates in **fixed hash order**, after two rules. Both rules are disclosed with the count each removes (`results/core-d2-test-set.json`; the selection script is `scripts/routeb/core2_select_tests.py`):

1. **Fix-area match, required.** A candidate's gold patch changes a source file some earlier task also changed (part of the 234 above). It removes the later tasks with no earlier counterpart, before the 234 are counted [established].
2. **No task that no model solved in existing data.** A candidate is dropped if public data shows it was tried and never solved. The source is the nebius OpenHands trajectories' `resolved` flags, about 10 runs on most tasks. Of the 234 candidates, **161 have data and 99 of those 161 are dropped**; the 73 without data stay [measured]. That leaves **135**, and 100 are taken.
   - The mini-SWE-agent source the owner named was **not available locally**: a search of the run directories and the repository found only the Plug lesson pool (125 repositories, no sqlglot) and no table of resolved flags. The one public mini-SWE-agent split with `resolved` flags (Open-SWE-Traces `minisweagent`) failed to download (an HTTP error from the host), and the SWE-bench experiments tree holds a single mini-SWE-agent run on Verified. Neither is used. Using more data could only drop more tasks [established].

**Hash order.** Candidates are sorted by sha256 of `core-d2:<instance_id>`; the first 100 kept are the test. 35 kept candidates are not taken. The script is `scripts/routeb/core2_select_tests.py`.

**Per repository** [measured]: Django 41, sqlglot 31, pennylane 14, dvc 8, conan 4, streamlink 2. The rule removes most streamlink and conan candidates, so results are reported per repository and the pooled claim leans on Django and sqlglot.

**Sampling of the data this rests on.** The nebius runs are a different agent and model, so "solved by some model" is a floor on how solvable a task is, not a prediction for Glimmer [established].

## Arms (paired by task; step cap 75, wall cap 45 min, reasoning low)

| Arm | Runs per task | What it is | Label |
|---|---|---|---|
| P: plain Glimmer | 2 | `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, no adapter | reference |
| A: Glimmer + Core adapter | 2 | LoRA (Route B's recipe, 16k) trained on teacher solutions of the six repositories' earlier tasks | under test |
| C: Glimmer + control adapter | 2 | the same recipe, the same data kind (Spark teacher solutions) and the same trained-token count, from OTHER repositories (none of the six, none of Plug's) | control |
| W: Glimmer + worked examples | 1, on 50 tasks (the first 50 of the 100 in the fixed selection hash order, sha256 of `core-d2:<instance_id>`, not the run order) | plain Glimmer with the teacher solutions of the 2 most similar earlier tasks of the same repository in the prompt (word overlap of issue texts; commands and results, about 6k tokens) | descriptive only [established] |

**Training data, stated plainly.**

- **Who ran the sessions.** The past sessions were run by Muse Spark (`muse-spark-1.3-contributor`, through the egress client) on each repository's earlier issues. Only sessions whose hidden tests passed are kept.
- **How they become rows.** Each is rendered turn by turn in Glimmer's chat format, and only the model's own turns are trained (routeb `sft_turns.py`, 80c61be).
- **No reflection step.** There is no reflection step on the sessions [established].

**Training set A, fixed (counts only, no adapter result)** [measured]. The per-repository cap of 14 is a maximum, not a target. The set was finalized on the passes that existed at **2026-10-29 20:43 PDT** (commit `c6850b7`), because training both adapters takes about 26 hours and the test must start Friday. It holds **68** Spark teacher sessions on earlier tasks: dvc 13, Django 13, streamlink 13, sqlglot 14, conan 7, pennylane 8. Its manifest sha256 is `864715e27f0adac270b95b3f1706d4a520e3b5cc6c8f56e142de9c7da290e83e` (`results/core-d2-train-A-counts.json`), with 747,227 tokens and 121,600 trained tokens at the 16k window.

- **Rule.** Teacher runs went interleaved across the four new repositories, each repository's earliest task first by `created_at`, and no repository took a new task after 14 passes. The order depended on dates only.
- **Existing sessions.** The earlier sqlglot and Django teacher passes joined: sqlglot's earliest 14 by date among the 161 earlier tasks (12 sqlglot passes lay outside that pool and were dropped), and all 13 Django passes.
- **Refusals.** No session is a test task or any of the 234 later candidates (0 refused) [established, by `core2_train_manifest.py`].

**Control set (arm C), fixed now** [established]. The sessions are Spark teacher runs on tasks of OTHER repositories (none of the six, none of Plug's), taken one task per repository in date order. Collection stops at a **finalization time** set before it ends and is trimmed by date order to match A's **68 sessions and 121,600 trained tokens**. A dated amendment will add ONLY the C manifest's sha256 and its counts, committed before the first D2 run; it changes no rule.

**Data mix (item 2).** A and C are both trained on teacher solutions only. Glimmer's own passes are not used in either arm, so the two arms match in kind, ratio and size by construction.

**Sampling (item 3).** Three screened tasks were rerun at temperature 0 on the same server (4 to 6 slots busy). Every model reply that could be compared was byte-identical to the screening run: 53 of 53, 59 of 59 and 43 of 43 replies in the first rerun, and 18, 21 and 5 replies in a second rerun that was cut short by an interruption [measured]. Temperature 0 repeats, so two identical runs would only be duplicates. Both runs of an arm therefore use **temperature 0.6 with a fixed seed per run**: seed = first 8 hex digits of sha256(`core2-d2:<instance_id>:<arm>:<run>`) [established, by construction].

- **Django.** The Django driver honors temperature and seed: its `Setting` puts both into every request (commit afbdee9, with a test). The test runner calls the driver's `run_once` with temperature 0.6 and the per-run seed, so Django runs the same sampling as the other repositories, and Django is pooled with them. The Django adapters are served under the driver's "personal" endpoint name [established].
- **Wall-cap caveat.** Runs that hit the 45-minute wall cap stopped at different steps (53 against 71 for one task) because Glimmer's speed changed with load, even though every compared reply was identical [measured]. Wall-cap hits are counted per arm.

**Order, cutoff and early stop**

- **Order.** All runs of a task go back to back. Tasks run in the order of sha256 of `core-d2-order:<instance_id>`.
- **Cutoff.** At **2026-11-01 18:00 PST (UTC-8)** no new task starts. That Sunday is the daylight-saving changeover (clocks fall back at 02:00), so 18:00 is Pacific Standard Time. The analysis uses every task whose runs all finished; incomplete tasks are excluded and counted. W's runs sit inside each task's back-to-back block, so a started W task finishes its W run; W is analyzed on the W tasks that finished before the cutoff, which may be fewer than 50, and no arm is cut for time.
- **Early stop.** After the first 50 complete tasks in run order (the seeded task order), arm A stops for all later tasks if the 95% CI of (A minus P) over those 50 lies wholly below 0. The runner checks this before every task and writes `early_stop.json` when it fires [established].

**Outcomes and voids (item 9)**

- A run that hits the step or wall cap counts as a fail.
- Only an infra or model_api error, or a container lost to the machine, makes a run void.
- A void run is rerun before the next task starts, at most twice. A run still void after two reruns drops its task from the analysis, and the report lists the task and the reason. A failed container scrub is an infra error and so is void (`scripts/routeb/core2_test_run.py`).
- Void counts are reported per arm.

## Primary analysis (co-primary, both needed for the claim)

- **Statistic.** For each task, d = (mean of the arm's runs) minus (mean of the reference's runs). The two co-primaries are **A minus P** and **A minus C**, each the mean of d over the analyzed tasks.
- **Interval.** 95% percentile bootstrap over tasks, 10,000 resamples, seed 20261101. [established]
- **Claim.** The headline is claimed only if BOTH lower bounds are above 0.
  - If A minus P clears but A minus C does not, the report says the gain cannot be told apart from training on any repository's solutions.
  - A CI below 0 is reported as harm.
- **Why A minus C is co-primary.** A minus P alone cannot tell the effect of the repository's own sessions from the effect of any teacher-solution training. C went through the same recipe on other repositories' sessions, so A minus C isolates the repository.

## Secondary (descriptive, no claim)

- C minus P.
- W minus P, on its 50 tasks. [established]
- Per repository and per kind (bug or feature), always beside the pooled number.
- Loops: runs with a command repeated 5 or more times.
- Empty patches.
- Steps to the first source edit.

## Smallest detectable gain (said plainly)

Computed at the expected plain pass rate, before any adapter result.

- **Formula, a worst-case bound.** No per-task paired SD exists yet, because no adapter has run. The bound takes the per-task variance of the difference of two arms' 2-run means as p(1-p), which ignores that tasks differ in difficulty and so overstates the spread. MDE = 2.8 x sqrt(p(1-p) / n) at 5% two-sided and 80% power [established]. The real SD from the first 30 complete tasks is reported beside it, and the bound is not revised.
- **Expected plain rate and its source** [measured, estimates only]:
  - sqlglot: 0.38 for plain Glimmer on the former 20-task test set.
  - Django: 39 of 66 graded plain later-task runs (0.59), from the collection runs.
  - The new repositories: unknown. 1 pass in 10 graded screening runs is too few to use.
  - The task rule (no never-solved tasks) tends to raise the rate. The planning range is therefore 0.25 to 0.50.
- **Result at n = 100 analyzed tasks:**

| Expected plain rate | MDE (points) |
|---|---|
| 0.15 | 10.0 |
| 0.25 | 12.1 |
| 0.38 | 13.6 |
| 0.50 | 14.0 |

- **Headline: about 12 to 14 points at n = 100; at n = 90, about 13 to 15 points** [established, by the formula].
- **Practical meaning.** Gains smaller than about 12 to 14 points read as "no detected difference". Published teacher-trajectory gains are +13 to +27 points [established].

## Runs and capacity

| Item | Runs |
|---|---|
| P2 + A2 + C2 on 100 tasks | 600 [established] |
| W1 on 50 tasks | 50 [established] |
| Test total | **650** [established] |
| Available after the Plug downstream test | about 690 [hypothesis] |

Machines and servers: the same Glimmer GGUF (sha256 `4cc57c0f…`, greedy parity checked) is served by **three servers**: the Strix, the 5080 and the laptop, each with the plain model and both adapters loaded [measured]. Containers run on the 5080 whatever the server. **Task-level assignment:** tasks are claimed in run order by whichever server is free, which depends on timing and never on outcomes; the claiming process runs ALL of that task's arms on its own server, so P, A and C of one task always share a server and the pairing holds. The server and a block id are recorded with every run. If a server stops answering, the task's block is voided whole and another server runs all its arms; a half-finished block is never scored. Per-server results are reported, and server is a stratum in the secondary analysis [established]. Servers differ in speed, so wall-cap hits are reported per server and arm.

## Data hygiene

- **History scrub.** Per-task images keep git history reaching the gold fix. Agent containers are scrubbed to the base commit's history before step 1, and a failed scrub voids the run [established].
- **Earlier runs.** An audit of all earlier trajectories found none that saw a later commit; the 11 runs on unscrubbed images were voided [measured].
- **Package install.** Agent and grader containers re-install the package without network [established].

## Known limits

- One shared adapter serves six repositories, so effects in any one repository are diluted.
- Teacher pass rates differ by repository [measured: 30/37 sqlglot, 13/16 Django; new repositories in progress].
- Tasks some model solved can still be unsolvable for Glimmer, so a floor near 0 on some tasks is possible.
