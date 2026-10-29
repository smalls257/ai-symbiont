# Pre-registration: Plug agent outcome, phase 2 (PLUG-AGENT-2)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any arm runs a task. After the freeze only a dated amendment may change anything, and an amendment cannot change the tasks, labels, arms, store, measures, the single primary contrast or the claim template.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Supersession

PLUG-AGENT-1 (`prereg/2026-10-29-plug-agent-outcome.md`, frozen at 52e6154, 29 tasks, one Glimmer run per arm) was **superseded by the owner on 2026-10-29 before any run**. No PLUG-AGENT-1 arm ran a task [established]. Its code (`scripts/routea/plug_agent_*.py`) and its Opus-fixed rules carry over unchanged unless a section below says otherwise. Neither prereg decides anything about round 3.

## Question

A coding agent works on a repository task. After a failed command it may receive one stored lesson from earlier tasks of the same repository. On tasks where a stored lesson applies, does a note picked by the judge (Llama 3.2 1B plus three LoRA adapters) make the agent repeat fewer known mistakes than no note?

## What changed from PLUG-AGENT-1

| Item | PLUG-AGENT-1 | PLUG-AGENT-2 |
|---|---|---|
| Agent | Glimmer on Strix | Muse Spark `muse-spark-1.3-contributor` via `symbiont.egress` and the spend ledger |
| Tasks | 29, validation repos of round 3 | later tasks of the nebius OpenHands repositories with a SWE-rebench image (count below) |
| Applies | a stored key matches a failure in any run | **Spark labels each (task, lesson) pair before any run** |
| Runs | 1 per arm | R per arm (below) |
| Primary | repeats per run, applies tasks, clustered by task | same, now defined on the frozen labels |
| Judge host | laptop loopback | 5080 loopback (CUDA), next to the harness |

## Frozen rules carried over from PLUG-AGENT-1 [established]

- Arms: `none` (floor), `none2` (A/A noise floor), `rag` (top 3 by the lexical ranker, always), `ranker` (round-3 thresholded ranker), `judge` (round-3 3-seed judge at its frozen thresholds from `selection.json`: judge 0.99, ranker 15.0).
- One primary contrast: `judge` minus the mean of `none` and `none2`. Everything else is exploratory.
- The judge being down stops the whole run with an error; the `judge` arm never proceeds with no notes (Silent Fallback).
- A void run (infra or model_api error) is requeued once; if still void, the task drops from all arms and is listed with its reason.
- Wall cap hits are reported per arm. A step or wall cap hit counts as unsolved in every arm alike.
- Full config pinning: one config file, sha256-checked by the runner, covers the model id, temperature, step limit, token cap, wall cap, thresholds, selection.json and adapter hashes, task-list hash, label-file hash, label-prompt hash, runs per arm, requeue cap, `llama-server` build n/a (Spark) replaced by the egress client commit.
- Scrubbed containers: every container resets to the task's base-commit history; a failed scrub voids the run.
- Fixed task order: sha256 of `plug-agent-2:<instance_id>`; per task all arms' runs (order by sha256 of `plug-agent-2:<instance_id>:<arm>:<run>`) finish before the next task; the cost cap is checked only between tasks.
- Hold-out: round 3's 40 scored repos are excluded from tasks, lessons and distractors.

## Tasks and store

- **Pool.** Tasks of the repositories in the nebius OpenHands exports on disk (532 repos, 3,863 tasks, 4,655 dates known across the round-4 date files [measured]). A task is a candidate when the repository has at least one earlier dated task [measured: 3,331 such later tasks]. SWE-rebench `created_at` orders tasks; an undated task is left out.
- **Image check.** Same as PLUG-AGENT-1: image pulls, gold passes, empty patch fails. In PLUG-AGENT-1, 34 of 51 instances had an image and 29 of 51 passed the check (57%) [measured]; the same rate on 3,331 gives about 1,900 candidates [hypothesis].
- **Store per task.** Only lessons mined from tasks created before the test task, same repository, plus distractors sampled from other repositories up to `PROMPT_LESSONS` (60), seeded by instance id. Never the task's own instance or a later one.
- **Lessons.** Template-built from the public pool (CC-BY-4.0, `spark_safe`). No AIDev text and no private session is read by any step.
- **Coordination with Plug round 4.** Round 4 scores the judge on situations from these same sessions; this test runs agents on the tasks. Both read the same exports; neither writes to the other's outputs. Round 4's frozen real-recurrence set (counts at d4aa9b4) is used here **only to order the pool for the 5080 image check**, never to select scored tasks after labels exist. Round 4's training tasks never enter this test's store as a test task; the controller lists any overlap in the report (the judge adapters were trained before these tasks were chosen [established]).

## "A lesson applies" (the owner's rule, frozen before any run)

- For each candidate task, Spark (`muse-spark-1.3-contributor`, temperature 0, through `symbiont.egress`, provenance `spark_safe=True`) sees the task's public SWE-rebench issue text and the template-built text of the candidate lessons (the task's same-repository store, at most 40 most recent) and answers, per lesson, `applies` or `does not apply`, with the question: "Could a developer fixing this issue plausibly run into the mistake this lesson describes?"
- The label prompt is committed as `scripts/routea/plug_agent2_label_prompt.md` and its sha256 is pinned. The labels are committed as `results/plug-agent-2-labels.json` (ids and labels only). **Both are committed before any agent run.** The same labels are used for every arm.
- A task is an **applies task** when at least one same-repository lesson is labeled `applies`. The scored set is the first `N_SCORED` applies tasks in the fixed task order (N below), decided before any agent run.
- Spark never sees AIDev text, private sessions, or agent trajectories in this step [established, by construction].
- Label cost: about 1,900 calls of roughly 3,500 input and 300 output tokens, about $1 [hypothesis].

## Agent and runs

- Agent: Muse Spark via the Core harness (mini-SWE-agent), parallel containers on the 5080 (24 cores, 10 to 15 at once), no Strix time. Temperature 0 requested; whether repeats are identical is not assumed (the A/A runs measure it) [hypothesis]. Step limit 75, wall cap 45 min, $0.15 per-run cap.
- Runs per task: `none` R, `none2` R, `judge` R, `rag` 2, `ranker` 2, with **R = 3** (justification: within-task variance dominates, see Sizing; each extra run per arm costs the same as 17% more tasks, and R = 3 gives each of the two floors a within-task spread estimate; R = 4 raises cost 23% for a 13% smaller standard error). [hypothesis]
- Judge host: the 5080, loopback, GPU, hashes checked against the config.
- Long drivers run detached on the 5080 (setsid nohup, log, done-file, resume from state) [established, standing rule].

## Measures

The one definition of a repeated known mistake from PLUG-AGENT-1 stands: key `(error class, program)`, empty parts never count; a known mistake has its key in the task's store; a repeat is a known mistake whose key already failed earlier in the same run.

- **Primary: repeats per run on applies tasks**, mean over a task's R runs per arm, then the paired difference per task; interval by percentile bootstrap over **tasks** (clustered by task; 10,000 resamples, seed 0).
- Secondary: solve rate over applies tasks; repeats over all candidates that ran; notes shown; tokens and cost; wall-cap hits per arm; the A/A difference beside every contrast.
- Exploratory: `rag` and `ranker` against `none`; `judge` against each.

## Sizing (stated before any run)

- Spark baseline: on 43 passing teacher runs, 0.58 error-class failures per run and 0.023 repeats per run [measured, passing runs only]. Glimmer baseline: 0.23 repeats per run over 328 sqlglot runs, 89% of runs with none; run-to-run within-task variance 0.52, between-task variance 0.26 [measured].
- With a Poisson-like variance of about twice the mean and a paired difference of the judge's R runs against 2R floor runs, the variance of a task's difference is about 0.5 times the per-run variance. At 50 applies tasks and a Spark baseline of 0.05 repeats per run, the smallest detectable reduction (80% power, two-sided 5%) is about 0.09 repeats per run [hypothesis]: more than the whole baseline. The test can detect an effect only if Spark's repeat rate on these tasks is at least about 0.3 per run.
- Therefore **the word "pilot" stays**, and the first step is a measured baseline (smoke test below). If the measured baseline is below the rate at which the planned N detects a halving, the report says so and makes no efficacy statement.

## Smoke test (at most $2, before the freeze, none arm only) [established]

25 candidate applies tasks disjoint from the scored set, `none` arm, 2 runs each, about 50 runs. It measures the Spark repeat rate, the failure rate, cost per run and wall time per run. Its runs are never scored and the scored set is chosen without them.

## Spend, runs and time (estimate, owner approval required)

| | Value |
|---|---|
| Scored applies tasks (N) | 50 [proposal; 80 if the smoke baseline is at least 0.15 repeats per run] |
| Runs per task | 3+3+3+2+2 = 13 |
| Scored runs | 650 (N = 50), 1,040 (N = 80) |
| Spark cost per run | about $0.04 mean [hypothesis], $0.15 cap (14 ledgered teacher runs: mean $0.028, median $0.022, p90 $0.067; unsolved runs run longer) [measured]. |
| Total Spark | about $26 (N = 50), $42 (N = 80), plus labels about $1 and smoke $2 [hypothesis] |
| Wall time on the 5080 | about 8 min per run [hypothesis, measured in the smoke], 12 in parallel: about 7 hours (N = 50), 12 hours (N = 80), if Spark rate limits and the other users of the 5080 allow |

## Claim template (fixed now)

"In a pilot of N tasks where Spark labeled a stored lesson as applying, the judge's repeated known mistakes per run differ from no note by [estimate, interval over tasks]; the test detects reductions of at least [MDE] per run." The report never says "the judge helps agents" and never uses speed-of-learning words.

## Not in this prereg

Any change to the judge, its thresholds or training; the 40 scored repos of round 3; Glimmer arms.
