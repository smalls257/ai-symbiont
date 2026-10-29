# DRAFT pre-registration: Core D2, does Glimmer solve more later issues of a repository after training on solved earlier ones?

**DRAFT, NOT FROZEN** (revision 2: the Opus proxy's 11 fix-first items). The freeze is a copy without "DRAFT" in its name, committed alone before any adapter result exists. After the freeze, only a dated amendment may change anything, and an amendment cannot change the tasks, arms, measures or decision rule. This supersedes `2026-10-29-core-solve-DRAFT.md`.

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

## Screening (set before any adapter result) [established]

1. **Rule.** One plain-Glimmer run per candidate at step cap 75. A pass drops the candidate as a near-certain pass; a failure keeps it. Screening runs never count as test runs, and P runs fresh in the test.
2. **Sampling.** sqlglot and the new repositories are screened at temperature 0. The Django runs used the driver's default sampling, because the Django driver had no temperature setting then. It has one now, and Django test runs use the test sampling.
3. **Django analysis.** Because of that difference, Django results are reported pooled and also separately.
4. **Picking the 100 test tasks.** If more than 100 candidates are kept, the 100 test tasks are the first in the order of sha256 of `core-d2:<instance_id>`. If fewer are kept, all of them are used. The per-repository count is reported, and the test set is committed before any adapter result.

## Arms (paired by task; step cap 75, wall cap 45 min, reasoning low)

| Arm | Runs per task | What it is | Label |
|---|---|---|---|
| P: plain Glimmer | 2 | `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, no adapter | reference |
| A: Glimmer + Core adapter | 2 | LoRA (Route B's recipe, 16k) trained on teacher solutions of the six repositories' earlier tasks | under test |
| C: Glimmer + control adapter | 2 | the same recipe, the same data kind (Spark teacher solutions) and the same trained-token count, from OTHER repositories (none of the six, none of Plug's) | control |
| W: Glimmer + worked examples | 1, on 50 tasks (the first 50 of the test order) | plain Glimmer with the teacher solutions of the 2 most similar earlier tasks of the same repository in the prompt (word overlap of issue texts; commands and results, about 6k tokens) | descriptive only [established] |

**Training data, stated plainly.**

- **Who ran the sessions.** The past sessions were run by Muse Spark (`muse-spark-1.3-contributor`, through the egress client) on each repository's earlier issues. Only sessions whose hidden tests passed are kept.
- **How they become rows.** Each is rendered turn by turn in Glimmer's chat format, and only the model's own turns are trained (routeb `sft_turns.py`, 80c61be).
- **No reflection step.** There is no reflection step on the sessions [established].

**Data mix (item 2).** A and C are both trained on teacher solutions only. Glimmer's own passes are not used in either arm, so the two arms match in kind, ratio and size by construction.

**Sampling (item 3).** If duplicate temperature-0 runs come out byte-identical (measured before the freeze, see below), both runs of an arm use temperature 0.6 with fixed seeds per run: seed = first 8 hex digits of sha256(`core-d2:<instance_id>:<arm>:<run>`). Otherwise they use temperature 0 [established once measured].

**Order, cutoff and early stop**

- **Order.** All runs of a task go back to back. Tasks run in the order of sha256 of `core-d2-order:<instance_id>`.
- **Cutoff.** At **2026-11-01 18:00 PT** no new task starts. The analysis uses every task whose runs all finished; incomplete tasks are excluded and counted.
- **Early stop.** When half the planned tasks are complete, arm A stops only if the 95% CI of (A minus P) lies wholly below 0. [established]

**Outcomes and voids (item 9)**

- A run that hits the step or wall cap counts as a fail.
- Only an infra or model_api error, or a container lost to the machine, makes a run void.
- A void run is rerun before the next task starts.
- Void counts are reported per arm.

## Primary analysis (co-primary, both needed for the claim)

- **Statistic.** For each task, d = (mean of the arm's runs) minus (mean of the reference's runs). The two co-primaries are **A minus P** and **A minus C**, each the mean of d over the analyzed tasks.
- **Interval.** 95% percentile bootstrap over tasks, 10,000 resamples, seed 20261101. [established]
- **Claim.** The headline is claimed only if BOTH lower bounds are above 0.
  - If A minus P clears but A minus C does not, the report says the gain cannot be told apart from training on any repository's solutions.
  - A CI below 0 is reported as harm.
- **Why A minus C is co-primary.** Screening keeps tasks plain Glimmer failed, so P sits near 0 on them by selection, and any change to the model can only gain on those tasks (regression to the mean). A minus C cancels that, because C went through the same screen.

## Secondary (descriptive, no claim)

- C minus P.
- W minus P, on its 50 tasks. [established]
- Per repository and per kind (bug or feature), always beside the pooled number.
- Loops: runs with a command repeated 5 or more times.
- Empty patches.
- Steps to the first source edit.

## Smallest detectable gain (said plainly)

The gain that can be detected depends on how often two arms disagree on a task, not on plain Glimmer's run-to-run spread.

- **Method.** Per-task differences of 2-run means have an SD of about 0.40-0.50 when 20-30% of task pairs disagree [hypothesis]. MDE = 2.8 x SD / sqrt(n) [established].
- **At n = 100 analyzed tasks: about 11-14 points.** At n = 90 it is about 12-15 points.
- **Practical meaning.** Gains smaller than about 12 points of solve rate will likely read as "no detected difference". Published teacher-trajectory gains are +13 to +27 points [established].

## Runs and capacity

| Item | Runs |
|---|---|
| P2 + A2 + C2 on 100 tasks | 600 [established] |
| W1 on 50 tasks | 50 [established] |
| Test total | **650** [established] |
| Available after screening and the Plug downstream test | about 690 [hypothesis] |

Machines: the Strix server and the 5080, the same GGUF (sha256 `4cc57c0f…`, greedy parity checked) [measured]. Each run records its machine and slot count.

## Data hygiene

- **History scrub.** Per-task images keep git history reaching the gold fix. Agent containers are scrubbed to the base commit's history before step 1, and a failed scrub voids the run [established].
- **Earlier runs.** An audit of all earlier trajectories found none that saw a later commit; the 11 runs on unscrubbed images were voided [measured].
- **Package install.** Agent and grader containers re-install the package without network [established].

## Known limits

- One shared adapter serves six repositories, so effects in any one repository are diluted.
- Teacher pass rates differ by repository [measured: 30/37 sqlglot, 13/16 Django; new repositories in progress].
- The screen keeps tasks plain Glimmer failed once, so some kept tasks may be unsolvable for every arm.
