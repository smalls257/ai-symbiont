# DRAFT pre-registration: Core D2, does Glimmer solve more new issues after learning from earlier ones?

**DRAFT, NOT FROZEN.** The freeze is a copy without "DRAFT" in its name, committed alone before any adapter result exists. After the freeze, only a dated amendment may change anything, and an amendment cannot change the tasks, arms, measures or decision rule. This draft supersedes `2026-10-29-core-solve-DRAFT.md` (on branch `routeb/general-lessons`).

Claim tags: [measured] = observed in our own run; [established] = known by construction or from the literature; [hypothesis] = a guess this run can support or refute.

## Claim

Glimmer is trained on solved runs of a repository's EARLIER issues: Muse Spark teacher solutions, plus Glimmer's own passes. Does it then solve more of that repository's LATER issues than plain Glimmer?

- The primary measure is the paired per-task solve rate.
- No speed-of-learning words are used.

## Repositories, earlier and later tasks [established]

There are six repositories:

- `tobymao/sqlglot`
- `django/django`
- `streamlink/streamlink`
- `conan-io/conan`
- `iterative/dvc`
- `PennyLaneAI/pennylane`

Tasks are SWE-rebench (or SWE-bench Verified for Django) instances that have images.

**How each repository is split** (`scripts/routeb/core2_sets.py`):

- **New repositories.** The first 55% of tasks by creation date are earlier; the rest are later. [established]
- **sqlglot.** The earlier tasks are the 40 collection tasks, kept as before. The later candidates are the later-by-date tasks with every collection task and every former test task removed.
- **Django.** The earlier tasks are SWE-Bench-CL positions 1-24. The later candidates are CL positions 25-49 plus 30 later SWE-bench Verified Django tasks ("15 min - 1 hour"), all scorer-checked.

**Fix-area match.** A later task is a candidate only if its gold patch changes a source file that some earlier task of the same repository also changed.

**No overlap.** No later task's run, patch or fix enters any training set. The training manifest refuses any test task [established, by construction].

## Screening (set before any adapter result) [established]

Rule:

1. Each candidate gets one plain-Glimmer run at temperature 0, step cap 75. A candidate whose run passes is dropped as a near-certain pass. A failed run keeps it.
2. Where two or more plain runs already exist, a task with mixed results is kept and the rest are dropped. This applies to the 20 sqlglot tasks of the former test set.
3. Django screening runs use the Django driver's default temperature, because that driver has no temperature setting. This is disclosed.

Screening runs never count as test runs: the plain arm runs fresh in the test.

**Picking the 100 test tasks.**

- If more than 100 candidates are kept, the first 100 in the order of sha256 of `core-d2:<instance_id>` form the test set.
- If fewer are kept, all of them do. The count and the per-repository breakdown are reported.
- The test set is committed before any adapter result.

## Arms (paired by task, temperature 0, step cap 75, wall cap 45 min, reasoning low)

| Arm | Runs per task | What it is | Label |
|---|---|---|---|
| P: plain Glimmer | 2 | `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, no adapter | reference |
| A: Glimmer + Core adapter | 2 | LoRA trained on the pooled earlier-task passes of all six repositories (Route B's recipe, 16k context) | under test |
| W: Glimmer + worked examples | 1 | plain Glimmer with the teacher's passing trajectories of the 2 most similar earlier tasks of the same repository in the prompt. Similarity is word overlap of the issue texts; examples are cut to their commands and results, about 6k tokens. Pre-registered as the fallback if A ties P | under test |
| C: Glimmer + control adapter | 1 | the same recipe and the same trained-token count on teacher passes from OTHER repositories (none of the six, none of Plug's) | control |

How the runs go:

- **Order.** All runs of a task go back to back. Tasks run in the order of sha256 of `core-d2-order:<instance_id>`, and the arms within a task run in a fixed rotation.
- **Fixed cutoff.** At **2026-11-01 18:00 PT** no new task starts. Analysis uses every task whose runs all finished; incomplete tasks are excluded and counted.
- **Early stop.** When half the planned tasks are complete, arm A stops only if the 95% CI of (A minus P) lies wholly below 0. Arms P, W and C continue. [established]
- **Errors.** A run ending on an infra or model_api error, a void container, or a machine sleep across its wall cap is void and re-queued, never scored.

## Primary analysis

- **Statistic.** For each task, (mean of A's runs) minus (mean of P's runs). The statistic is the mean over tasks.
- **Interval.** 95% percentile bootstrap over tasks, 10,000 resamples, seed 20261101. [established]
- **Claim.** "Glimmer solves more new issues after training on earlier ones" is claimed only if the lower bound is above 0. A CI that straddles 0 is reported as no detected difference; a CI below 0 is reported as harm.

## Secondary (descriptive)

- W minus P, and A minus C, with the same interval.
- Per repository and per kind (bug or feature).
- Loops: runs with a command repeated 5 or more times.
- Empty patches.
- Steps to the first source edit (a run with no edit counts as the step cap).

## Smallest detectable gain (alpha 0.05, power 0.8, paired)

MDE = (1.96 + 0.84) x sqrt(2v / (r x n)), with n = 100 tasks and r = 2 runs per arm [established]. Plain Glimmer's measured run-to-run spread puts v at 0.05-0.10 [measured], which gives an MDE of **6.3-8.9 points** of solve rate [measured inputs, computed]. At temperature 0 the spread may be smaller and the MDE smaller [hypothesis].

## Runs and machines

| Item | Runs |
|---|---|
| Test | 100 tasks x (2 + 2 + 1 + 1) = 600 [established] |
| Screening (already running) | about 250 |
| Capacity by the cutoff | about 1,030 [hypothesis] |

The machines are the Strix server and the 5080 desktop. Both serve the same GGUF (sha256 `4cc57c0f…`) through llama.cpp, with greedy-parity checked [measured]. Each run records its machine and slot count. Arms are not assigned by machine; a task's runs may use either.

## Data hygiene

- **History scrub.** Per-task images keep git history that reaches the gold fix. Every agent container is scrubbed to the base commit's history before step 1, and a failed scrub voids the run [established]. sqlglot uses its shared image re-checked-out at the base commit [established].
- **Earlier runs.** An audit of every earlier trajectory found no run that saw a commit after its task. The 11 runs on unscrubbed images were voided [measured].
- **Package install.** Agent and grader containers re-install the checked-out package without network (`pip install --no-deps -e .`), so src-layout repositories can be tested at all [established].

## Known limits

- One shared adapter serves six repositories, so repository-specific effects are diluted.
- Teacher pass rates differ by repository [measured: 30/37 sqlglot, 13/16 Django; new repos in progress].
- The screening rule keeps tasks plain Glimmer failed once, so some kept tasks may be unsolvable for any arm.
