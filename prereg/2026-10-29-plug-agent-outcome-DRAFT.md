# Pre-registration: Plug agent outcome, phase 1 (PLUG-AGENT-1)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any arm runs a task. After the freeze only a dated amendment may change anything, and an amendment cannot change the tasks, arms, store, measures or decision words below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

This is the small first phase of the downstream test that `prereg/2026-10-29-plug-judge.md` leaves out. The full version (about 150 tasks per arm [hypothesis]) is a later prereg, `PLUG-AGENT-2`, sized from this phase's spread. Neither phase decides anything about round 3, and round 3's claim never implies agent success. The build is specified in `docs/research/2026-10-29-plug-agent-outcome-interface.md`.

## Amendments

(none at freeze)

## Question

A coding agent (mini-SWE-agent driven by Spark) works on a repository task. After each failed command it may receive one stored lesson as a note. Does a note picked by the judge help it solve more tasks, or repeat fewer known mistakes, than no note, the ranker's own pick, or a basic retrieval of the top three lessons? This phase is descriptive: it measures effect sizes and spread to size phase 2. No speed-of-learning words.

## Tasks and store

- **Tasks.** The SWE-rebench task instances of round 3's 10 validation repos: 51 instances [measured]. An instance stays if its image pulls and its hidden tests pass with the gold patch and fail with none; the expected count is 30 to 40 [hypothesis]. The build lists every dropped instance with its reason.
- **These repos set both thresholds.** The judge's and the thresholded ranker's thresholds were fitted on these same 10 repos' situation items (round 3's validation fit) [established]. The agent tasks differ from those items, but the arms are not tested on repos their thresholds never saw; phase 2 is.
- **Never touched.** Round 3's 40 scored repos are excluded: no task, no lesson, no distractor. That keeps this phase out of the judge's scored run [established, by construction].
- **Store per task (only earlier instances).** Every lesson of the pool except the 40 scored repos' lessons, the lessons mined from the task's own instance, and the lessons mined from any instance created after the task's own (SWE-rebench `created_at`; an instance without a date is left out). A lesson is never shown on its own task or on a task that predates it [established, by construction]. The build logs, per task, how many lessons each rule removed.
- **Privacy.** Lessons are from the public nebius OpenHands pool (CC-BY-4.0, `spark_safe`). No private or local session reaches a prompt.

## Agent settings (identical in every arm)

One config file, `results/plug-agent-1-config.json`, holds every setting. The runner refuses a config with another hash, and every arm reads the same file. A blank field blocks the freeze [established, by construction].

| Setting | Value |
|---|---|
| Model | `muse-spark-1.3-contributor` (Contributor tier), reasoning effort low |
| Temperature | 0 |
| Step limit | 75 |
| Wall cap | 45 min |
| Output tokens per reply | 4,096 |
| Per-run cap | $0.15, enforced by the spend ledger before each call; about 1.5M prompt tokens at the Contributor price [established] |
| Seed | 20261029. The chat API takes no seed, so it is recorded but not sent; task, arm and store order come from the sha256 and instance-id seeds below |
| Phase cap | $6.00 (see Spend) [established] |

config sha256: `CONFIG_SHA256`

## Order and the cost cap

Tasks run in the order of sha256 of `plug-agent-1:<instance_id>`. For each task all four arms run, in the order of sha256 of `plug-agent-1:<instance_id>:<arm>`, before the next task starts. The cost cap is checked only between tasks, so every finished task has all four arms; a run that hits the per-run cap counts as unsolved, in every arm alike. A run that ends on an infra or model_api error is void and re-queued, never scored [established, by construction].

## Arms (one run per task per arm, paired by task)

| Arm | Note after a failed command | Label |
|---|---|---|
| `none` | nothing (`WrapMode.PLAIN`) | floor |
| `rag` | the top 3 lessons by the lexical ranker, always | reference (basic retrieval) |
| `ranker` | the ranker's top lesson if its top score reaches the thresholded ranker's round-3 validation threshold | reference |
| `judge` | the judge's top shortlisted lesson if its seed-mean P(yes) reaches the judge's round-3 validation threshold | under test |

Thresholds and adapters are the ones `plug_r3_run.py fit` wrote into round 3's validation amendment (`selection.json`, amendment 1 at 1b6a655), with round 3's frozen selection rule [established]:

- **Judge.** The 3-seed ensemble: adapters `judge-s0`, `judge-s1` and `judge-s2`, scored by the mean of their P(yes), at threshold 0.99. The per-seed thresholds (0.991, 0.99 and 0.99) are not used.
- **Thresholded ranker.** Top inverse-document-frequency score at least 15.0.

Nothing is tuned on these tasks. Notes are each lesson's stored text, verbatim.

**Store size** [hypothesis]. The earlier-instances-only rule leaves early tasks fewer than `PROMPT_LESSONS` candidates: 12 to 60 in the dry run over the 34 imaged tasks. The ranker's inverse-document-frequency weights are computed over the store, so on a small store its top score, and with it the 15.0 threshold, may mean something different. The report gives each task's store size beside its arms.

## Measures

- **Solved.** The task's hidden tests pass on the agent's final patch (the Core harness's grader).
- **Repeated known mistakes.** Per run, the failed commands whose failure key (error class plus the command's program) matches a lesson in that task's store. Counted the same way in every arm, including `none`.
- **Notes shown.** Per run, for each arm; a run with no failed command shows nothing in any arm.
- **Cost.** Input and output tokens per run, from the shared client's size log.

## Analysis (descriptive, no decision)

For each arm against `none`, and `judge` against `ranker` and `rag`: the paired difference in solve rate and in repeated mistakes per run, each with a percentile bootstrap interval over tasks (10,000 resamples, seed 0) [established]. Every row prints beside `none`. The report's sentence says "in a pilot of N tasks" and gives intervals, never "the judge helps agents". The per-task spread of each difference sizes PLUG-AGENT-2 [hypothesis].

## Spend and machine

- **Runs.** 4 arms times the kept tasks, in the order above: about 120 to 160 runs [hypothesis].
- **Endpoint.** Spark through the Contributor endpoint and the shared egress client (`symbiont.egress.post_json`), the Core agent's existing mini-SWE-agent setup. Paid spend is the owner's call.
- **Cost.** Core's Spark teacher runs, same client and same agent loop, averaged 211k prompt and 11.8k output tokens per run: $0.024 at the Contributor price ($0.10 per million in, $0.20 per million out; 57 runs) [measured]. 4 arms times 34 tasks at that mean is about $3.3 [hypothesis].
  - The phase cap is $6.00. [established]
  - The runner checks this phase's own ledger spend between tasks.
  - It starts a task only if all four arms fit under the cap at $0.15 each. [established]
  - It stops and reports the tasks it finished.
  - The owner's total ledger cap ($60) still applies [established].
- **Judge.** The judge (Llama 3.2 1B, `meta-llama` instruct weights as trained, plus three LoRA adapters) runs as a loopback service on the laptop (Apple MPS, bf16), next to the harness. It answers about 10 pairs per failed command [established, the shortlist size].
  - **Matches the desktop.** On 200 round-3 validation pairs its seed-mean P(yes) matched the desktop CUDA scores: max difference 0.0018, no pair crossing 0.99 [measured].
  - **Speed.** One call of 10 pairs took 1.9 s [measured].
- **Deadline.** Built and run before Nov 4; it must not delay round 3's scored run, which never waits for it.

## Not in this prereg

- PLUG-AGENT-2, the full test with about 150 tasks per arm [hypothesis], on repos neither the judge nor this phase used.
- Any change to the judge, its thresholds or its training.
