# Habitat home robot: results for "set the table" and "house rules" (scored once, 2026-11-02 and 2026-11-03)

Claim tags: [measured], [established], [hypothesis]. Row labels: floor, reference or under test. Counts and ids: `results/habitat-set-table-b3.json` and `results/habitat-house-rules.json`. Preregs: `prereg/2026-11-02-habitat-frozen.md` plus amendments 1 to 3 (`prereg/2026-11-02-habitat-amendment-1-build.md`, `prereg/2026-11-02-habitat-amendment-2-v3.md`, `prereg/2026-11-03-habitat-amendment-3-all-lessons.md`). The preregs are copies of the files frozen in the run directory; the sha256 and freeze time of each original are in the closing note of the copy and in the results files. The copies were committed after the runs, so git history does not show the freeze; the recorded hash and timestamp do.

## Method
- **Agent.** Muse Spark (`muse-spark-1.3-contributor`, reasoning effort low), one action per turn. Each prompt holds the task, the house layout, the last 8 actions and the current text observation, plus symbiont's notes in the with arm. The arms differ only in the notes [established].
- **World.** The rules of the world (what a move, a pick, an open drawer or a refused action does, and what the pet event changes) live in a pure-Python text model, `world.py`. Habitat-Sim 0.3.3 with the ReplicaCAD apartment (CC BY-NC 4.0) renders the recorded actions; it does not decide outcomes. Observations are template text, with magic grasp [established]. The third-arm episodes ran on the pure model with no simulator at all, which gives the same outcomes for the same seed, start place and pet schedule [established].
- **Notes.** The with arm used the plugin's own `symbiont hook UserPromptSubmit`, one session per episode, at planning time and again after a pet event or a refused action. At most one rule is delivered per prompt, once per session.
- **Spend.** Contributor tier, run cap $15 [established].

## Set the table (Task B v3, fixed layout)
The robot clears four cluttered items off the dining table, then sets 12 tableware items hidden in closed containers, carrying one at a time, with a budget of twice the best possible number of actions (142). A pet event once knocks or carries an item away. The hiding places are the same in every episode, like one real home; the seed changes only the robot's start place and the pet's timing and target.

- **Lessons.** Two episodes with no notes (gate seeds 611 and 612) both failed: 5 of 12 items each [measured]. Sixteen lessons were mined mechanically from those failures and written up by Spark's own reflection; none was hand-written [measured].
- **Comparison.** Five new seeds (621 to 625) per arm, same start places and pet events across arms.

| Arm | Label | Episodes solved | Items set (of 60) | Invalid actions | Prompt tokens per episode |
|---|---|---|---|---|---|
| No notes | floor | 0 of 5 [measured] | 38 [measured] | 39 [measured] | about 90,500 [measured] |
| symbiont notes, selected and timed | reference | 4 of 5 [measured] | 58 [measured] | 16 [measured] | about 134,000 [measured] |
| All 16 lessons in every prompt | under test | 4 of 5 [measured] | 59 [measured] | 3 [measured] | about 144,000 [measured] |

- The with arm and the all-lessons arm both failed only seed 624 (10 and 11 of 12 items, out of budget) [measured]. At this size, selecting and timing the notes did not beat pasting every lesson into the prompt. That was the pre-registered reading rule for the third arm: a match means the selection adds nothing measurable here [measured]. The all-lessons arm costs more prompt tokens every turn; the sizes are in the table.
- **Randomized hiding places (Task B v2, seeds 541 to 545).** With the hiding places drawn fresh per seed, 1 of 5 episodes was solved without notes and 1 of 5 with them (the with arm ran on the earlier build dc35e1f) [measured]. Notes about where things were last time cannot help when the places change. No lift there.

## House rules (Task A)
Six items must be put away; four owner-only rules cover five of them (mugs, the cat's bowl, the towel, the cast-iron pan), and the sixth item is an inferable control. One learning episode with no notes broke the rules, then the owner's corrections were applied, and Spark wrote the lessons from them. Six new seeds (301 to 306) per arm.

| Arm | Label | House-rule violations (5 chances per episode, 6 episodes) | Control item right |
|---|---|---|---|
| No notes | floor | 30 [measured] | 6 of 6 [measured] |
| Notes from the corrections | under test | 0 [measured] | 6 of 6 [measured] |

- Steps per episode were 33 to 53 without notes and 30 to 32 with them [measured].

## Caveats
- **One home, one model, one simulated apartment.** Five seeds per arm for the table, six for the rules. No significance test was planned or run [measured].
- **Fixed layout.** The 4 of 5 is a same-home result: the lessons say where this home keeps things. With randomized hiding places the result was 1 of 5 either way, so it does not carry to a changing layout [measured].
- **The house-rules corrections were scripted by us**, one per violated rule, not given by a real owner. The notes carry the rules nearly verbatim, so this shows the agent keeps a rule it was told, not that it can infer one [hypothesis].
- **The mug lesson needed a revision.** It did not fire on the item prompt at first, so Spark revised its trigger terms once after a diagnostic. This is disclosed in the prereg [measured].
- **Layout was chosen after seeing the randomized result.** Amendment 2 fixed the layout by owner instruction after the randomized runs, so the fixed-layout comparison is pre-registered but was motivated by the earlier outcome [established].
- **Pure-model arm.** The all-lessons arm did not use the simulator; the with and without arms did. The world rules are the same code, but it is a different execution path [established].
- **Reused arms.** The all-lessons arm was added in Amendment 3, written before its episodes, and reuses the without and with episodes unchanged [established].
- No transcripts, prompts or model-written text are in `results/`; the files hold counts, ids and labels only [established].
