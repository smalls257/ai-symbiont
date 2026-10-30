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
| Agent | Glimmer on Strix | Glimmer Q4_K_M on the owner's laptop (llama.cpp, 2 slots), containers on the 5080; Spark only writes the labels |
| Tasks | 29, validation repos of round 3 | later tasks of repositories with mined recurrences (pool below) |
| Applies | a stored key matches a failure in any run | Spark labels each (task, lesson) pair before any run |
| Runs | whole runs, one per arm | **branch points**: one shared prefix per task, then every arm continues from the same state |
| Primary | repeats per run | the share of branch points at which the same key fails again within the window |
| Judge host | laptop loopback | wherever the 5080 GPU is not used (laptop CPU or Metal) |

## Frozen rules carried over from PLUG-AGENT-1 [established]

- Arms: `none` (floor), `none2` (A/A noise floor), `rag` (top 3 by the lexical ranker, always), `ranker` (round-3 thresholded ranker), `judge` (round-3 3-seed judge at its frozen thresholds from `selection.json`: judge 0.99, ranker 15.0).
- One primary contrast: `judge` minus the mean of `none` and `none2`. Everything else is exploratory and makes no claim.
- The judge being down stops the whole run with an error. It is recorded as `judge_down`, never as "no note" and never as a `none` run (Silent Fallback).
- A void run (infra or model_api error, not a cap hit) is requeued once; if still void, the task drops from all arms and is listed with its reason.
- A continuation that reaches the step limit or the wall cap **counts its repeats up to the cutoff; it is not void**, in every arm alike. Cap hits are reported per arm. [established]
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

The prefix run's **first known mistake** is the branch point; it happens before any note could be shown by it, in every arm, because all arms share the prefix. **The primary indicator, per arm and branch point, is 1 if the same key fails again within the W = 15 steps after the branch point, else 0.** The unit is the task (one branch point per task). The primary contrast is the paired difference per task, `judge` minus the mean of `none` and `none2`. Counts of branch points, of tasks without one, and of branch points where the judge showed a note are reported.

- **Inference [established, declared now].** An exact paired sign test on the discordant tasks (judge vs the mean of the floors counted as discordant only when both floors agree), with a BCa interval for the mean paired difference (10,000 resamples, seed 0). Clustered by task, never by continuation. No claim from any secondary.
- **Secondary, no claims.** `rag` and `ranker` against the floors; repeats of any keyed failure in the window; notes shown; steps to the next edit; tokens and wall time per continuation; the A/A disagreement rate.

## Smoke test and the one stop rule (frozen before the smoke test)

- 25 applies tasks chosen by sha256 order of `plug-agent-2-smoke:<instance_id>` from the 360 applies tasks, `none` arm, whole runs, 1 run each on the laptop Glimmer (2 runs each only if fewer than 10 runs hit a first known mistake). **These 25 tasks are excluded from scoring.** Their runs are never scored. [hypothesis]
- It reports [hypothesis]: runs with a first known mistake, the conditional repeat share, the share of failures with no key, the top keys, the applies count, cost and wall time per run.
- **Stop rule.** Go to the scored phase only if at least **10 smoke runs** hit a first known mistake **and** at least **30 percent** of those repeat it. Otherwise stop: the report says Glimmer does not make enough repeat mistakes at known keys to carry this test, and the owner decides the next step. More tasks are not the fallback. Only N may change after this rule is read out.

## Agent, infrastructure and branch points

- **Agent.** Plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M` (GGUF sha256 matches the Strix copy; the hash is pinned in the config), served by llama.cpp on the owner's laptop (version 0.8.0, build 11960, commit 8642541b2; 2 slots of 32k, flash attention, `--jinja`), bearer key from the environment, never logged. Containers (mini-SWE-agent, scrubbed, no network) run on the 5080 CPU. Reasoning low, temperature 0, step limit 75, wall cap 45 min, 4,096 tokens per reply. Fresh arms only: no run of Core's on the Strix is mixed in [established].
- **Speed, measured on one task** [measured]: about 14 tok/s generation and about 115 tok/s for uncached prompt tokens with one stream; with two streams each runs at 8 to 9 tok/s (total about 1.25 times one slot). One 53-step run took 18 min. Two slots give about 4 full runs per hour.
- **Branch point.** For each task, the `none` prefix run proceeds until its first known mistake (key in the key rule, from an `applies`-labeled lesson). At that point the driver commits the container (`docker commit`) and keeps the message history. Every arm (`none`, `none2`, `judge`, `rag`, `ranker`) starts a new container from that image with the same history, receives its arm's note for the failed command (none: nothing), and continues for **W = 15 further steps**. The state each arm faces is identical; only the note differs. A prefix run that ends with no known mistake yields no branch point and is reported. Notes after the branch point follow the PLUG-AGENT-1 rules per arm.
- **Whether temperature 0 repeats** is not assumed: `none` and `none2` are two continuations of the same state; their disagreement rate is the A/A noise floor [hypothesis]. Where an arm shows no note, its continuation equals `none` up to that noise.
- **Judge.** Round 3's frozen judge, run on the laptop CPU or Metal or any host that is not the 5080 GPU (reported to the controller); hashes checked against the config. A down judge stops the run and is recorded as `judge_down`.
- **Images.** Pulled just in time, size checked first (limit 8 GB, disk floor 60 GB), removed right after the task's last branch; never more than the scored set needs.
- Every long driver runs detached on the 5080 (setsid nohup, log, done-file, resume from state) [established].

## Sizing (stated before the scored run; N is the one number that may still move)

- **What one branch point costs** [hypothesis]: the prefix (about 25 steps when it reaches a known mistake, a whole run of 18 min when it does not) plus four to five continuations of 15 steps (about 5 min each), or about 1 hour of one slot when the prefix reaches a known mistake in 3 of 10 runs.
- **Branch points available.** About 36 usable hours on 2 slots (aggregate 1.25 times one slot) give about 35 to 40 branch points at a prefix hit rate of 0.3, and about 60 at 0.5. The hit rate is measured in the smoke test.
- **The judge only changes a branch point where it speaks.** At the frozen threshold it answered about a third of the applicable situations in round 3's validation [measured, round 3]. Where it is silent its continuation equals `none`, so at most that third of branch points can show a difference.
- **Consequence** [hypothesis]: with about 40 branch points, a judge note at about 13 of them, and a repeat share p0 around 0.4, at most about 5 pairs can differ, and an exact paired test needs about 6 discordant pairs in one direction. **The test cannot confirm an effect smaller than a near-total prevention at the points where the judge speaks.** It is a pilot in the strict sense: it measures p0, the note rate and the A/A floor, and shows whether a note can change the agent's next steps at all. The word "pilot" stays; the report states the minimum detectable difference from the measured numbers.

## Spend and time (estimate)

| | Value |
|---|---|
| Spark | labels done: $0.12 for 667 tasks [measured]. No other Spark call. |
| Smoke | 25 tasks, `none` arm, 1 run each (extended to 2 runs only if fewer than 10 runs hit a first known mistake): 6 to 12 hours on 2 slots [hypothesis] |
| Scored | about 36 hours of the laptop's two slots [hypothesis] |
| Laptop | one heavy job only (the Glimmer server); caffeinate, on power |

## Claim template (fixed now)

"In a pilot of N tasks where Spark labeled a stored lesson as applying, at the first known mistake, the judge's share of continuations that made it again within 15 steps differs from no note by [estimate, BCa interval, sign-flip p]; the test detects differences of at least [MDE]." The report never says "the judge helps agents" and never uses speed-of-learning words.

## Not in this prereg

Any change to the judge, its thresholds or training; the 40 scored repositories of round 3; Glimmer arms (the agent is Glimmer by the owner's decision of 2026-10-29).
