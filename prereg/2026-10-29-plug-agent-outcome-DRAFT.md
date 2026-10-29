# Pre-registration: Plug agent outcome, phase 1 (PLUG-AGENT-1)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any arm runs a task. After the freeze only a dated amendment may change anything, and an amendment cannot change the tasks, arms, store, measures, the single primary contrast or the claim template below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

This is the small first phase of the downstream test that `prereg/2026-10-29-plug-judge.md` leaves out. The full version (about 150 tasks per arm [hypothesis]) is a later prereg, `PLUG-AGENT-2`, sized from this phase's spread. Neither phase decides anything about round 3, and round 3's claim never implies agent success. The build is specified in `docs/research/2026-10-29-plug-agent-outcome-interface.md`.

## Amendments

(none at freeze)

## Question

A coding agent (mini-SWE-agent driven by plain Glimmer, the owner's local model) works on a repository task. After each failed command it may receive one stored lesson as a note. Does a note picked by the judge make it repeat fewer known mistakes than no note? That is the one primary contrast. The ranker's pick and a basic retrieval of the top three lessons are exploratory references. This is a pilot: it measures effect sizes and spread to size phase 2, and it is not powered to decide anything. No speed-of-learning words.

## Tasks and store

- **Tasks.** The SWE-rebench task instances of round 3's 10 validation repos: 51 instances [measured]. An instance stays if its image pulls and its hidden tests pass with the gold patch and fail with none; the task check kept **29** [measured]: 17 dropped for no SWE-rebench image, 3 because the gold patch does not resolve, 2 for a grader error (no pytest summary). The check ran after the package-reinstall fix; an earlier check on unfixed images was voided. `plug_agent_tasks.py` lists every dropped instance with its reason.
- **These repos set both thresholds.** The judge's and the thresholded ranker's thresholds were fitted on these same 10 repos' situation items (round 3's validation fit) [established]. The agent tasks differ from those items, but the arms are not tested on repos their thresholds never saw; phase 2 is.
- **Never touched.** Round 3's 40 scored repos are excluded: no task, no lesson, no distractor. That keeps this phase out of the judge's scored run [established, by construction].
- **Store per task (only earlier instances).** Every lesson of the pool except the 40 scored repos' lessons, the lessons mined from the task's own instance, and the lessons mined from any instance created after the task's own (SWE-rebench `created_at`; an instance without a date is left out). A lesson is never shown on its own task or on a task that predates it [established, by construction]. The build logs, per task, how many lessons each rule removed.
- **Privacy.** Lessons are from the public nebius OpenHands pool (CC-BY-4.0, `spark_safe`). No private or local session reaches a prompt.

## Agent settings (identical in every arm)

One config file, `results/plug-agent-1-config.json`, holds every setting. The runner refuses a config with another hash, and every run reads the same file. A blank field blocks the freeze [established, by construction].

| Setting | Value |
|---|---|
| Agent | plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M` on the owner's Strix server, no adapter, reasoning low [established] |
| Temperature | 0. Whether repeated temperature-0 runs are identical is not assumed: the A/A runs below measure it [hypothesis] |
| Step limit | 75 [established] |
| Wall cap | 45 min [established] |
| Output tokens per reply | 4,096 [established] |
| Seed | 20261029, for the order seeds below only [established] |

**Also pinned in the config, so a changed input changes the hash** [established, by construction]:

- the judge threshold (0.99), the ranker threshold (15.0), the number of judge seeds (3) and the shortlist size (10);
- `PROMPT_LESSONS` (60);
- the sha256 of round 3's `selection.json` and of each judge adapter file (`judge-s0`, `judge-s1`, `judge-s2`);
- the sha256 of the sorted kept-task list (29 ids);
- the `llama-server` build (`b10820-74a7c897f`);
- the runs per arm and the void requeue cap.

config sha256: `f5018960b94238243ffad9a6ecbe31a2fef587585c7ca4fce7d9a11bad3dc4ea`

## Order and the cost cap

Tasks run in the order of sha256 of `plug-agent-1:<instance_id>`. For each task all five runs (`none`, `none2`, `rag`, `ranker`, `judge`) run, in the order of sha256 of `plug-agent-1:<instance_id>:<arm>`, before the next task starts. The cost cap is checked only between tasks, so every finished task has all five runs.

**Outcomes and voids.** Implemented in `scripts/routea/plug_agent_run.py` (tests: `tests/scripts/test_plug_agent_run_wiring.py`); the runner writes `voids.jsonl` and `dropped.jsonl` for the report.

- A run that hits the step or wall cap counts as unsolved, in every arm alike.
- **Wall-cap hits are reported per arm**, with the server's slot count at the time, because Glimmer contention with Core can lengthen a run. Solved is reported as scored; the report states each arm's wall-cap hits and whether dropping them changes any contrast [established].
- An infra or model_api error makes a run void. A void run is requeued **once**, before the next task starts.
- If a run is still void after its one requeue, the task **drops from all five runs** and the report lists it with its reason. The task is never scored on the arms that finished.
- **The judge being down stops the whole run with an error.** The `judge` arm never proceeds with no notes, since that would score a `none` run under the judge's name (Silent Fallback) [established, by construction].

## Arms (one run per task per arm, paired by task)

| Arm | Note after a failed command | Label |
|---|---|---|
| `none` | nothing (`WrapMode.PLAIN`) | floor |
| `none2` | nothing; a second run of the floor on the same task | A/A noise floor |
| `rag` | the top 3 lessons by the lexical ranker, always | exploratory reference (basic retrieval) |
| `ranker` | the ranker's top lesson if its top score reaches the thresholded ranker's round-3 validation threshold | exploratory reference |
| `judge` | the judge's top shortlisted lesson if its seed-mean P(yes) reaches the judge's round-3 validation threshold | under test |

`none` and `none2` are identical in everything but the run. Their difference is the A/A noise floor: the spread any other contrast must be read against, and the test of whether temperature 0 repeats [hypothesis]. The primary contrast uses the mean of the two floor runs. The exploratory contrasts (`rag`, `ranker`) use `none` alone, so they are noisier than the primary.

Thresholds and adapters are the ones `plug_r3_run.py fit` wrote into round 3's validation amendment (`selection.json`, amendment 1 at 1b6a655), with round 3's frozen selection rule [established]:

- **Judge.** The 3-seed ensemble: adapters `judge-s0`, `judge-s1` and `judge-s2`, scored by the mean of their P(yes), at threshold 0.99. The per-seed thresholds (0.991, 0.99 and 0.99) are not used.
- **Thresholded ranker.** Top inverse-document-frequency score at least 15.0.

Nothing is tuned on these tasks. Notes are each lesson's stored text, verbatim.

**Store size** [hypothesis]. The earlier-instances-only rule leaves early tasks fewer than `PROMPT_LESSONS` candidates: 12 to 60 in the dry run over 34 imaged tasks (29 after the check). The ranker's inverse-document-frequency weights are computed over the store, so on a small store its top score, and with it the 15.0 threshold, may mean something different. The report gives each task's store size beside its runs.

## Measures

**One definition of a repeated known mistake** (the build spec points here and defines nothing of its own):

- A failed command's **key** is `(error class, program)`: the error class from `lessons.ERROR_CLASS` and the program from `normalise_command`. A command with an empty error class or an empty program has no key and is never counted.
- A **known mistake** is a failed command whose key equals the key of some lesson in the task's store.
- A **repeat** is a known mistake whose key already failed earlier in the same run. The note arms show their note at the first occurrence, so a repeat is a mistake the note was there to stop.
- Per run, count the repeats. The count is made from the logged failure keys and the task's store, the same way in every arm [established, by construction].

**A lesson applies to a task** when some stored lesson's key matches a failure made in ANY of the five runs of that task. The set is the same for every arm, so the floor arm no longer chooses it. It is still mildly arm-influenced: it includes the `judge` run's own failures, and a task where no run made a known mistake has nothing to repeat [established]. The report gives how many of the 29 tasks it holds [established].

**Primary: repeats per run, on the tasks where a lesson applies.** Secondary: the same count over all 29 tasks, which is not selected on any run. If fewer than 10 tasks apply, the all-tasks count becomes the headline and the subset is secondary [established].

**Other measures:**

- **Solved** (secondary). The task's hidden tests pass on the agent's final patch (the Core harness's grader).
- **Notes shown.** Per run, for each arm; a run with no failed command shows nothing in any arm.
- **Cost.** Input and output tokens and wall time per run, from the server's replies.
- **Wall-cap hits per arm**, as above.

## Analysis (pilot, one primary contrast)

**The single primary contrast: `judge` minus the mean of `none` and `none2`, in repeats per run, on the tasks where a lesson applies.** Everything else is exploratory: `rag` and `ranker` against `none`, `judge` against `ranker` and `rag`, and solve rate over all 29 tasks. No exploratory contrast supports a claim. Each contrast has a percentile bootstrap interval over tasks (10,000 resamples, seed 0) [established]. Every row prints beside `none`, and the A/A difference (`none` minus `none2`) prints beside every contrast.

**Pilot, and its size** [hypothesis]. With 29 tasks, a paired difference in solve rate can only be told from zero if it is about 30 points or more. A pilot of this size is not powered below that. **There is no minimum detectable difference for the repeat-count primary.** The 30 points holds only for solve rate. The repeat count's spread is unknown until the A/A runs show it, and PLUG-AGENT-2 is sized from that spread [established].

**Claim template (fixed now).** "In a pilot of N tasks, on the repos that set its thresholds, the judge's repeats per run differ from no note by [estimate, interval]; not powered below about 30 points." The report never says "the judge helps agents".

## Spend and machine

- **Runs.** 5 runs times the 29 kept tasks: 145 runs (116 for the four note arms plus 29 for the A/A run) [established].
- **Endpoint.** Plain Glimmer on the owner's Strix server over the LAN, the Core agent's mini-SWE-agent harness. No paid API call [established].
- **Glimmer time.** Core's plain Glimmer runs take about 6 minutes of wall time per run [measured]. 145 runs is about 14-15 slot-hours [hypothesis].
  - The phase shares Glimmer with Core and runs when the coordinator schedules it.
  - The runner stops between tasks at the hour budget the coordinator sets, and reports the tasks it finished.
- **Judge.** The judge (Llama 3.2 1B, `meta-llama` instruct weights as trained, plus three LoRA adapters) runs as a loopback service on the laptop (Apple MPS, bf16), next to the harness. It answers about 10 pairs per failed command [established, the shortlist size].
  - **Matches the desktop.** On 200 round-3 validation pairs its seed-mean P(yes) matched the desktop CUDA scores: max difference 0.0018, no pair crossing 0.99 [measured]. The adapter files the laptop serves must hash to the config's adapter hashes.
  - **Speed.** One call of 10 pairs took 1.9 s [measured].
- **Deadline.** Built and run before Nov 4; it must not delay round 3's scored run, which never waits for it.

## Not in this prereg

- PLUG-AGENT-2, the full test with about 150 tasks per arm [hypothesis], on repos neither the judge nor this phase used.
- Any change to the judge, its thresholds or its training.
