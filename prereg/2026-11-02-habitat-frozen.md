# Habitat home-robot demo: pre-registration (FROZEN before any comparison episode)

Frozen 2026-11-02 after the gate baselines and the zero-Spark pre-flight; owner go received. Amendments are new dated files.

## Common setup
Agent: Muse Spark (muse-spark-1.3-contributor, reasoning effort LOW), one action per turn, stateless prompt =
task + house layout + last 8 actions + current text observation (+ symbiont notes in the WITH arm). Arms are
identical except the notes. World: Habitat-Sim 0.3.3, ReplicaCAD apt_0 (CC BY-NC 4.0; non-commercial demo),
navmesh paths, articulated drawers/doors, magic grasp (disclosed). Seeds, layouts and the pet schedule come from
the seed and are identical across arms. Observations and skill results are synthetic template text.
WITH arm notes come from the plugin's own `symbiont hook UserPromptSubmit` (install: ai-symbiont main dc35e1f),
one session per episode: at planning time (one prompt per item for Task A; three planning questions for Task B)
and again after a pet event or a refused action. Harness failures (simulator, ssh, API outage) are retried once,
then recorded as infrastructure errors and excluded from the model comparison (listed, never scored as failures).
Spend: Contributor tier, run cap $15, ledger ~/symbiont-runs/spend/ledger.jsonl. [established]

## Task A: tidy-up with owner-only house rules
6 items, start places from the seed; 4 rules cover 5 items (mugs -> upper cupboard 3; cat's bowl -> floor by the
front door; towel -> chest drawer middle left; cast-iron pan -> counter drawer 1); sneakers -> shoe rack is an
inferable control. Budget 60. Learning episode: gate-tidy-101 (no lessons). The owner's corrections are SCRIPTED
text, one per violated rule; Spark writes the lessons (with applies_to terms); saved via lessons/add.
Comparison: N = 6 seeds per arm (301-306). PRIMARY: house-rule violations per episode (rule items not in the
required place at the end, of 5). Secondary: placed wrong, steps, invalid actions. Every episode reported.

## Task B v2: get the apartment ready for four guests (strategy failures, not tribal knowledge)
Dining table starts with 4 cluttered items that must go to inferable homes (mail -> chest top, magazine ->
bookshelf, tv remote -> tv stand, dirty bowl -> kitchen counter) before tableware may be placed. 12 tableware items
(4 plates, 4 cups, 4 forks) hidden in randomly chosen closed containers (15 containers, at most 2 each), fresh layout
per seed; contents visible only while standing at an open container; carry capacity 1; no map in the prompt.
Budget = 2 x the omniscient optimum for the seed (about 140-146 actions). A seeded pet event fires once (knock an [established]
already-set item to the floor by the table, or carry it to another room); it is scripted-random, identical across
arms, and only a neutral event line reaches the agent. The apartment has no doors between rooms and no living-room
cabinet; hiding places are kitchen cupboards/drawers/fridge, the dining-area pantry cabinet and the entry chest.
Gate (no lessons): gate-host-511 succeeded (105/140); gate-host-515 failed (9/12); gate3-host-525 failed (9/12);
gate3-host-522 failed (7/12). Lessons come ONLY from Spark's own failed gate episodes: mechanical failure
mining plus Spark's reflection; no hand-written text.
Comparison: N = 5 seeds per arm (541-545). PRIMARY: success rate (all 12 set, table cleared, within budget);
secondary: items set, steps used, invalid actions, cost. Every episode reported.

## Showcase rule (real recordings)
The FIRST seed of each task (301 for A, 541 for B) is the showcase pair, chosen now, not by outcome; both arms are
recorded at 1080p with the Fetch robot during their real comparison runs. Captions carry episode ids.

## Claims
Tagged [measured] only for what the tables show; this house, these tasks, one model; no speed-of-learning claims.
Fetch robot: hab_fetch (CC BY-NC-SA 4.0, Fetch Robotics); ReplicaCAD: CC BY-NC 4.0.

## Frozen details added at pre-flight (before comparison runs)
- Pre-flight (zero Spark): A: all 4 house-rule notes fire at planning, step 0, before the first action (fired_by: shared terms).
  B: lessons mined from gate2 episodes, replayed on held-out gate3 episodes: 6 planning notes at step 0.
- Task A lessons: Spark authored them from the scripted corrections; the mug lesson did not fire for the item prompt, so
  Spark revised its applies_to terms once after a diagnostic (the prompts it failed to match were shown). Disclosed.
- Task B lessons: mechanical mining + Spark reflection on the failed gate episodes 515, 522, 525 (22 lessons saved, none hand-written).
  Six planning questions (batch.py ITEM_PROMPTS) are sent at episode start; refused actions and pet events can fire further notes.
  The plugin delivers at most one rule per prompt, once per session, so planning notes are capped at the number of questions.
- Bugs fixed during the audit (asset-write race between parallel simulators, budget init, spurious notes from the help text of
  an invalid action) are listed in results/preflight_audit.md.

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 0b874f159031144a8c286b57aea5ba824c724c6e8731d43bf55c82e1b0ef2331) are the claim tags appended to the lines that state a number and this note; no rule, arm, seed or threshold differs. The original's recorded freeze time is its file modification time, 2026-11-02T21:11:36-08:00. The committed copy was added after the runs, so git history does not show the freeze; the hash and timestamp do.
