# Pre-registration: Plug agent outcome, phase 1 (PLUG-AGENT-1)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any arm runs a task. After the freeze only a dated amendment may change anything, and an amendment cannot change the tasks, arms, store, measures or decision words below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

This is the small first phase of the downstream test that `prereg/2026-10-29-plug-judge.md` leaves out. The full version (about 150 tasks per arm [hypothesis]) is a later prereg, `PLUG-AGENT-2`, sized from this phase's spread. Neither phase decides anything about round 3, and round 3's claim never implies agent success. The build is specified in `docs/research/2026-10-29-plug-agent-outcome-interface.md`.

## Amendments

(none at freeze)

## Question

A coding agent (mini-SWE-agent driven by plain Glimmer, the owner's local model) works on a repository task. After each failed command it may receive one stored lesson as a note. Does a note picked by the judge help it solve more tasks, or repeat fewer known mistakes, than no note, the ranker's own pick, or a basic retrieval of the top three lessons? This phase is descriptive: it measures effect sizes and spread to size phase 2. No speed-of-learning words.

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
| Agent | plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M` on the owner's Strix server, no adapter, reasoning low [established] |
| Temperature | 0 [established] |
| Step limit | 75 [established] |
| Wall cap | 45 min [established] |
| Output tokens per reply | 4,096 [established] |
| Seed | 20261029. The order seeds below use it; llama-server sampling at temperature 0 needs none [established] |

config sha256: `CONFIG_SHA256`

## Order and the cost cap

Tasks run in the order of sha256 of `plug-agent-1:<instance_id>`. For each task all four arms run, in the order of sha256 of `plug-agent-1:<instance_id>:<arm>`, before the next task starts. The cost cap is checked only between tasks, so every finished task has all four arms; a run that hits the step or wall cap counts as unsolved, in every arm alike. A run that ends on an infra or model_api error is void and re-queued, never scored [established, by construction].

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

- **Primary: repeated known mistakes, on tasks where a lesson applies.**
  - A *known mistake* is a failed command whose failure key (error class plus the command's program) matches a lesson in the task's store.
  - A *repeat* is a known mistake whose key already failed earlier in the same run. The note arms show their note at the first occurrence, so a repeat is a mistake the note was there to stop.
  - *Tasks where a lesson applies* are the tasks whose `none` run makes at least one known mistake. The floor arm decides this, never a treated arm.
  - Per run, count the repeats. Counted the same way in every arm [established, by construction].
- **Solved** (secondary). The task's hidden tests pass on the agent's final patch (the Core harness's grader).
- **Notes shown.** Per run, for each arm; a run with no failed command shows nothing in any arm.
- **Cost.** Input and output tokens and wall time per run, from the server's replies.

## Analysis (descriptive, no decision)

Primary: on the tasks where a lesson applies, the paired difference in repeats per run for each arm against `none`, and for `judge` against `ranker` and `rag`. Secondary: the same paired differences in solve rate over all tasks, each with a percentile bootstrap interval over tasks (10,000 resamples, seed 0) [established]. Every row prints beside `none`. The report's sentence says "in a pilot of N tasks" and gives intervals, never "the judge helps agents". The per-task spread of each difference sizes PLUG-AGENT-2 [hypothesis].

## Spend and machine

- **Runs.** 4 arms times the kept tasks, in the order above: about 120 to 160 runs [hypothesis].
- **Endpoint.** Plain Glimmer on the owner's Strix server over the LAN, the Core agent's mini-SWE-agent harness. No paid API call.
- **Glimmer time.** Core's plain Glimmer runs take about 6 minutes of wall time per run at 4 parallel slots [measured]. 4 arms times 34 tasks is about 136 runs, about 13-14 Glimmer hours [hypothesis].
  - The phase shares Glimmer with Core and runs when the coordinator schedules it.
  - The runner stops between tasks at the hour budget the coordinator sets, and reports the tasks it finished.
  - No paid API is used [established].
- **Judge.** The judge (Llama 3.2 1B, `meta-llama` instruct weights as trained, plus three LoRA adapters) runs as a loopback service on the laptop (Apple MPS, bf16), next to the harness. It answers about 10 pairs per failed command [established, the shortlist size].
  - **Matches the desktop.** On 200 round-3 validation pairs its seed-mean P(yes) matched the desktop CUDA scores: max difference 0.0018, no pair crossing 0.99 [measured].
  - **Speed.** One call of 10 pairs took 1.9 s [measured].
- **Deadline.** Built and run before Nov 4; it must not delay round 3's scored run, which never waits for it.

## Not in this prereg

- PLUG-AGENT-2, the full test with about 150 tasks per arm [hypothesis], on repos neither the judge nor this phase used.
- Any change to the judge, its thresholds or its training.
