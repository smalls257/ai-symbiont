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
- **Never touched.** Round 3's 40 scored repos are excluded: no task, no lesson, no distractor. That keeps this phase out of the judge's scored run [established, by construction].
- **Store per task (leave one instance out).** Every lesson of the pool except the 40 scored repos' lessons and the lessons mined from the task's own instance. A lesson is never shown on the task it came from [established, by construction].
- **Privacy.** Lessons are from the public nebius OpenHands pool (CC-BY-4.0, `spark_safe`). No private or local session reaches a prompt.

## Arms (one run per task per arm, paired by task)

| Arm | Note after a failed command | Label |
|---|---|---|
| `none` | nothing (`WrapMode.PLAIN`) | floor |
| `rag` | the top 3 lessons by the lexical ranker, always | reference (basic retrieval) |
| `ranker` | the ranker's top lesson if its top score reaches the thresholded ranker's round-3 validation threshold | reference |
| `judge` | the judge's top shortlisted lesson if its seed-mean P(yes) reaches the judge's round-3 validation threshold | under test |

Thresholds and adapters are the ones `plug_r3_run.py fit` writes into round 3's validation amendment. Nothing is tuned on these tasks. Notes are each lesson's stored text, verbatim.

## Measures

- **Solved.** The task's hidden tests pass on the agent's final patch (the Core harness's grader).
- **Repeated known mistakes.** Per run, the failed commands whose failure key (error class plus the command's program) matches a lesson in that task's store. Counted the same way in every arm, including `none`.
- **Notes shown.** Per run, for each arm; a run with no failed command shows nothing in any arm.
- **Cost.** Input and output tokens per run, from the shared client's size log.

## Analysis (descriptive, no decision)

For each arm against `none`, and `judge` against `ranker` and `rag`: the paired difference in solve rate and in repeated mistakes per run, each with a percentile bootstrap interval over tasks (10,000 resamples, seed 0) [established]. Every row prints beside `none`. The report's sentence says "in a pilot of N tasks" and gives intervals, never "the judge helps agents". The per-task spread of each difference sizes PLUG-AGENT-2 [hypothesis].

## Spend and machine

- **Runs.** 4 arms times the kept tasks: about 120 to 160 runs [hypothesis].
- **Endpoint.** Spark through the Contributor endpoint and the shared egress client (`symbiont.egress.post_json`), the Core agent's existing mini-SWE-agent setup. Paid spend is the owner's call.
- **Cost.** Runs times measured tokens per run times the Contributor price. Before the freeze the Core agent fills in its measured mean tokens per mini-SWE-agent run, the price and the total, as a cap; the runner stops at the cap and reports the runs it finished.
- **Judge.** The judge (Llama 3.2 1B plus three LoRA adapters) runs as a loopback service next to the harness: CUDA on the 5080, or CPU on the laptop. About 10 pairs per failed command [established, the shortlist size].
- **Deadline.** Built and run before Nov 4; it must not delay round 3's scored run, which never waits for it.

## Not in this prereg

- PLUG-AGENT-2, the full test with about 150 tasks per arm [hypothesis], on repos neither the judge nor this phase used.
- Any change to the judge, its thresholds or its training.
