# Amendment 2 (2026-11-02): Task B v3, fixed home layout (owner instruction)

Supersedes the abandoned build re-run of Amendment 1 (stopped by the owner before any episode finished; its partial Spark calls are in the ledger, none were scored).
The Task B v2 results with randomized hiding places (results/cmpB, build dc35e1f) remain as recorded.

- Task B v3 = Task B v2 (clear the cluttered table first; 12 tableware items hidden in closed containers; carry 1; budget 2x optimum; [established]
  seeded pet event; no map in observations; contents visible only while standing at an open container) BUT the hiding places are
  FIXED for all episodes, like one real home: plates in upper cupboard 3 / counter drawer 2 / chest bottom-left / chest bottom-right
  (one each), cups in chest bottom-left / upper cupboard 3 / pantry cabinet / counter drawer 2, forks in chest top-right (x2) /
  chest bottom-right / chest middle-left. The layout comes from the constant seed "host3-fixed-layout" (code: world.py _init_host).
  The seed varies ONLY the robot's start place (kitchen floor, floor by the front door, floor by the sofa, floor by the dining table,
  desk, tv stand) and the pet's kind, timing and target (scripted-random, identical across arms).
- Build: ai-symbiont main afd5b7876ca188addde0c14060f33e20ee2d1f2c (PR #63 not merged at install time), fresh venv2, sha asserted by
  build_check.py (output in build_check.log). Isolated service: port 8795, data dir symdata-v3.
- Steps: (1) this note; (2) GATE: WITHOUT x2 (seeds 611, 612), Spark must fail cold; (3) LEARN: lessons only from the failed gate episodes via
  mechanical mining plus Spark's own reflection (never hand-edited), store snapshot; (4) zero-Spark replay: which notes fire, when,
  fired_by, before the relevant actions; (5) comparison WITHOUT x5 vs WITH x5 fresh, seeds 621-625 (not the gate seeds);
  (6) real renders of the first seed pair only if WITH improves.
- Measures: PRIMARY success rate (all 12 set, table cleared, within the budget); secondary items set, steps used, invalid actions, cost.
  Every episode reported; infrastructure errors excluded and listed. Budget cap for this step about $0.40. [established]

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 32f8083933f7ed34aeecb90639b32fffb72e2d88f458d795b5a96510416d5e92) are the claim tags appended to the lines that state a number and this note; no rule, arm, seed or threshold differs. The original's recorded freeze time is its file modification time, 2026-11-02T22:34:37-08:00. The committed copy was added after the runs, so git history does not show the freeze; the hash and timestamp do.
