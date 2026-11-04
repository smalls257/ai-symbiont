# Amendment 3 (2026-11-03): third arm ALL-LESSONS for Task B v3 ("is this just RAG?")

Written before any episode of the arm. Owner-approved. Question: does symbiont's selection and timing of notes matter, or would pasting every lesson into the prompt do as well?

- Arm ALL-LESSONS: the same 16 lessons as the WITH arm (results/store_snapshot_v3_afd5b78.db, table authored, project habitat-host3), each rendered exactly as symbiont renders a note
  ("[symbiont] In this repo: <text>"), ALL placed in the NOTES FROM SYMBIONT section of EVERY prompt from step 0. No symbiont service, no relevance selection, no timing: nothing arrives later.
- Everything else identical to the existing arms: Task B v3 fixed layout, seeds 621-625 (same start places and pet events), muse-spark-1.3-contributor, effort LOW, 8-action history, budget 2x optimum. [established]
- Reused as-is: WITHOUT x5 (results/cmpB3, floor) and WITH x5 (results/cmpB3, reference: symbiont build afd5b78). New: ALL-LESSONS x5 -> results/cmpB3all (under test).
- PRIMARY: success count (of 5) against WITH 4/5 and WITHOUT 0/5. Secondary: items set, invalid actions, prompt tokens per episode (the cost of always sending everything). No renders for this arm. Budget about $0.15. [established]
- Reading rule, fixed now: ALL-LESSONS matching WITH means the selection/timing adds nothing measurable at this size; clearly below WITH means selection/timing matters; no claim beyond this home, these 16 lessons, 5 seeds.

- Execution path (owner instruction, to leave the GPU to the re-render): the episodes run against the PURE world model (agent.PureSim over world.py: no simulator, no GPU, no recording). world.py decides every outcome in the real server too (the simulator only draws it), so with the same seed, start place and pet schedule the episodes are outcome-equivalent to the sim-backed WITH and WITHOUT arms.

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 2cb8dfb7f945fdbd6990b25f75a9b25a0bed1b15c678b2227889402eba44024f) are the claim tags appended to the lines that state a number and this note; no rule, arm, seed or threshold differs. The original's recorded freeze time is its file modification time, 2026-11-03T02:21:05-08:00. The committed copy was added after the runs, so git history does not show the freeze; the hash and timestamp do.
