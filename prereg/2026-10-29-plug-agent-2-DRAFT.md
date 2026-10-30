# Pre-registration: Plug agent outcome, phase 2 (PLUG-AGENT-2)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any arm runs a scored task. After the freeze only a dated amendment may change anything, and an amendment cannot change the pool, labels, arms, store, measures, the single primary contrast, the stop rule or the claim template. Only the number of scored tasks N may change after the smoke test.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Supersession

PLUG-AGENT-1 (`prereg/2026-10-29-plug-agent-outcome.md`, frozen at 52e6154, 29 tasks, one Glimmer run per arm) was **superseded by the owner on 2026-10-29 before any run**. No PLUG-AGENT-1 arm ran a task [established]. Its code (`scripts/routea/plug_agent_*.py`) and its Opus-fixed rules carry over unchanged unless a section below says otherwise. Neither prereg decides anything about round 3.

## Question

A coding agent works on a repository task. After a failed command it may receive one stored lesson from earlier tasks of the same repository. When the agent has just made a mistake that a stored, applicable lesson describes, does a note picked by the judge (Llama 3.2 1B plus three LoRA adapters) make it less likely to make the same mistake again than no note?

## What changed from PLUG-AGENT-1

| Item | PLUG-AGENT-1 | PLUG-AGENT-2 |
|---|---|---|
| Agent | Glimmer on Strix | Muse Spark `muse-spark-1.3-contributor` via `symbiont.egress` and the spend ledger |
| Tasks | 29, validation repos of round 3 | later tasks of repositories with mined recurrences (pool below) |
| Applies | a stored key matches a failure in any run | Spark labels each (task, lesson) pair before any run |
| Runs | 1 per arm | R per arm |
| Primary | repeats per run on applies tasks | the share of runs, among those that hit a first known mistake, that make the same mistake again |
| Judge host | laptop loopback | 5080 loopback (CUDA) |

## Frozen rules carried over from PLUG-AGENT-1 [established]

- Arms: `none` (floor), `none2` (A/A noise floor), `rag` (top 3 by the lexical ranker, always), `ranker` (round-3 thresholded ranker), `judge` (round-3 3-seed judge at its frozen thresholds from `selection.json`: judge 0.99, ranker 15.0).
- One primary contrast: `judge` minus the mean of `none` and `none2`. Everything else is exploratory and makes no claim.
- The judge being down stops the whole run with an error. It is recorded as `judge_down`, never as "no note" and never as a `none` run (Silent Fallback).
- A void run (infra or model_api error, not a cap hit) is requeued once; if still void, the task drops from all arms and is listed with its reason.
- A run that reaches the step limit, the wall cap or the $0.15 per-run cap **counts as unsolved with its repeats counted up to the cutoff; it is not void**, in every arm alike. Cap hits are reported per arm. [established]
- Full config pinning: one config file, sha256-checked by the runner. It holds the model id, temperature setting, step limit, token cap, wall cap, per-run cap, **the total dollar cap**, thresholds, `selection.json` and adapter hashes, the pool and task-list hashes, the label-file hash, the label-prompt hash, the key-rule file hash, runs per arm, the requeue cap and the egress client commit.
- Scrubbed containers: every container resets to the task's base-commit history; a failed scrub voids the run.
- Fixed task order: sha256 of `plug-agent-2:<instance_id>`; per task all arms' runs (order by sha256 of `plug-agent-2:<instance_id>:<arm>:<run>`) finish before the next task starts; the cost cap is checked only between tasks.

## Pool (defined by a rule, independent of round 4's scored set)

- **Repositories.** Repositories in the nebius OpenHands exports on disk (CC-BY-4.0, `spark_safe`) that (1) are **not** among the 125 repositories of round 3's pool, (2) are not one of Core's six repositories, (3) have at least two dated tasks (SWE-rebench `created_at`), and (4) have at least one **loose** real recurrence by the counter at d4aa9b4 (a failure in a later, different task of the same repository whose normalized command and error line match a lesson of an earlier task). The rule counts recurrences per repository only; it does not use round 4's primary situation set or its scored selection. Result: 118 repositories [measured].
- **Round-3 judge training.** Round 3 trained the judge on the lessons of its 60 meta-train repositories, all inside its 125-repository pool, and fitted thresholds on its 10 validation repositories (also inside the pool). Rule (1) removes every one of those, so **no test instance's own session was in the judge's training or threshold fit** [established, by construction]. The pool script asserts the empty intersection and writes the count. Round 4 trains separate adapters; this test uses round 3's frozen judge only.
- **Later tasks.** Every dated task of those repositories except the repository's earliest: 946 [measured].
- **Candidates.** A later task whose SWE-rebench row has a docker image and for which at least one lesson was mined from an earlier instance of the same repository exists. The pool summary lists the counts dropped by each reason; two export files that the reader could not parse are skipped and listed.
- **Store per task.** Same-repository lessons mined from instances created strictly before the task (distinct failures, the 40 most recent), in template prose (`Lesson.text`). Never the task's own instance or a later one. Round 3's 40 scored repositories do not occur in the pool.
- **Privacy.** Only public SWE-rebench task text and template-built lessons reach Spark. No AIDev text and no private session is read by any step [established].
- **Coordination with Plug round 4.** Round 4 scores the judge on situations from the same sessions; this test runs agents on the tasks. Neither writes the other's outputs. The controller receives the list of this test's repositories to compare with round 4's scored repositories; overlap is reported, not removed.

## "A lesson applies" (frozen before any run)

- For each candidate task, Spark (`muse-spark-1.3-contributor`, temperature 0, through `symbiont.egress`, provenance `spark_safe=True`) sees the public issue text (cut at 6,000 characters) and the numbered template-prose lessons of the task's store, and labels each lesson `applies` or `does_not_apply`. The prompt is `scripts/routea/plug_agent2_label_prompt.md`, committed and pinned by sha256 before the first call.
- **Unusable replies.** A reply that is not the exact JSON object with one valid label per lesson is retried once. If still unusable the task is **excluded and listed with its reason**. A failed label is never read as `does_not_apply` [established].
- The labels are committed (`results/plug-agent-2-labels.json`: ids and labels only) **before the smoke test and before any scored run**; the runner checks the label-file hash.
- **Hand check.** The author reads about 30 labeled pairs, chosen by sha256 order of pair ids, before the freeze and reports only the counts of agreed and disagreed labels in the commit message. The check does not change a label.
- A task is an **applies task** when at least one lesson of its store is labeled `applies`.

## Known mistake and repeat (frozen before the smoke test)

- A failed command's **key** is `(error class, program, target file)`: `lessons.ERROR_CLASS` on the error line, `normalise_command` for program and first path-like argument. **A key with an empty error class, an empty or "-" program, or an empty or "-" target file does not exist and never counts as known.** This excludes generic keys such as `(ModuleNotFoundError, python)`, which say only that a Python command failed [established, by construction]. The rule is `scripts/routea/plug_agent2_keys.py` (tested), pinned by hash.
- A **known mistake** is a failed command with a key equal to the key of a lesson **labeled `applies` for this task** (same repository).
- The share of failures with no key and the most frequent keys are reported from the smoke test.

## Primary outcome (arm-blind)

Per run, take the first known mistake (a known mistake happens before any note could be shown by it, in every arm). **Among runs that hit a first known mistake, the primary indicator is 1 if the same key fails again later in the run, else 0.** The unit is the task: the mean of the indicator over a task's runs of one arm that hit a first known mistake. The primary contrast is the paired difference per task, `judge` minus the mean of `none` and `none2`, over tasks that have at least one such run in both. Counts of conditioned runs and tasks are reported per arm. Where a run's first known mistake follows an earlier note, it stays in (the conditioning is on a failure, not on notes) and the number of such runs is reported per arm.

- **Inference [established, declared now].** A paired sign-flip permutation test over tasks (100,000 flips, seed 0) with a BCa interval for the mean paired difference (10,000 resamples, seed 0). Clustered by task, never by run.
- **Secondary, no claims.** Repeats of any keyed failure per run; solve rate; the same primary for `rag` and `ranker` against the floors; notes shown; tokens and cost; wall-cap hits.

## Smoke test and the one stop rule (frozen before the smoke test)

- 25 applies tasks chosen by sha256 order of `plug-agent-2-smoke:<instance_id>` from the candidates, `none` arm only, 2 runs each (about 50 runs), at most $2. **These 25 tasks are excluded from scoring.** Their runs are never scored. [hypothesis]
- It reports [hypothesis]: runs with a first known mistake, the conditional repeat share, the share of failures with no key, the top keys, the applies count, cost and wall time per run.
- **Stop rule.** Go to the scored phase on Spark only if at least **10 smoke runs** hit a first known mistake **and** at least **30 percent** of those repeat it. Otherwise stop: the report says the Spark agent does not make enough repeat mistakes to power this test, and the fallback (a weaker agent, Glimmer, which repeated 0.23 times per run on sqlglot) goes to the owner. More tasks are not the fallback. Only N may change after this rule is read out.

## Agent and runs

- Muse Spark via the Core harness (mini-SWE-agent), parallel containers on the 5080 (10 to 15 at once), no Strix time. Temperature 0 requested; whether repeats are identical is not assumed (the A/A runs measure it) [hypothesis]. Step limit 75, wall cap 45 min, $0.15 per-run cap, total dollar cap pinned in the config.
- Runs per task: `none` 3, `none2` 3, `judge` 3, `rag` 2, `ranker` 2. Justification: within-task variance dominates [measured, Glimmer: within 0.52, between 0.26 per run]; three runs per primary arm give each floor its own spread, and a fourth raises cost 23% for a 13% smaller standard error [hypothesis].
- Judge: the 5080, loopback, CUDA, only when the GPU is free; hashes checked against the config.
- Every long driver runs detached on the 5080 (setsid nohup, log, done-file, resume from state) [established].

## Sizing

N is set after the smoke test from its measured conditional share and conditioned-run rate. Before it, the sizing is [hypothesis]: the primary is a proportion among conditioned runs; with conditioned-run rate c per run, p0 the none share and 3 runs per arm, a task contributes about 3c conditioned runs in the judge arm and 6c in the floors; the standard error of the paired difference at N tasks is about sqrt(p0(1-p0)(1/3c + 1/6c)/N) before clustering, and the report states the minimum detectable difference from the measured p0 and c, with the intra-task correlation estimated from the A/A pair. "Pilot" stays unless that minimum detectable difference is 15 points or less.

## Spend and time (estimate)

| | Value |
|---|---|
| Labels | about 700 calls, under $1 [hypothesis] |
| Smoke | 50 runs, at most $2 [hypothesis] |
| Scored runs | 13 per task: N = 50 gives 650 runs, about $26 at $0.04 per run [hypothesis; ledgered teacher runs: mean $0.028, median $0.022, p90 $0.067, passing runs only] [measured] |
| Wall time on the 5080 | about 8 min per run, 12 in parallel: about 7 hours at N = 50 [hypothesis, to be measured in the smoke] |

## Claim template (fixed now)

"In a pilot of N tasks where Spark labeled a stored lesson as applying, among runs that made a known mistake, the judge's share that made it again differs from no note by [estimate, BCa interval, sign-flip p]; the test detects differences of at least [MDE]." The report never says "the judge helps agents" and never uses speed-of-learning words.

## Not in this prereg

Any change to the judge, its thresholds or training; the 40 scored repositories of round 3; Glimmer arms (unless the stop rule hands the decision to the owner, who would then get a new dated prereg).
