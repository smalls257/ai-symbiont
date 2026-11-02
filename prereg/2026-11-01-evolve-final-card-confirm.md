# Pre-registration: does a card Muse Spark assembled from rules it screened itself improve its play on held-out maps? (plays Freedoom via ViZDoom)

**FROZEN 2026-10-31.** Code pinned at 5dc5fc8650455d40e4e0fd33424205b9a7f94927 (this commit's parent; `scripts/evolve/confirm_test.py check` enforces it). Committed alone, before any card game of this test was played; the no-card games it reuses were played earlier by the held-out test. An amendment cannot change the arm, card, goal, maps, split, partitions, seeds, condition, fitness, pairing, bootstrap or decision rule.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## The propose-screen-assemble loop that made the card (analysis maps only)

1. **Goal (Spark).** From outcome shares of its own no-card games, Spark wrote (sha256 `56f4e9999a82aa53df5a5f3b672bd5cb61ac9952f8b4e5e2d5f229b17e6140ab`): "A good game is one where I reach the exit. A bad game is one where I die or end alive without reaching the exit."
2. **Causal proposal (Spark, one call).** Given the goal, the good-versus-bad tallies and tallies of what it chose to do (command shares, commands per reply, shots with nothing in view), it separated symptoms from choosable actions, stated cause-to-outcome links with confidence, and proposed six candidate one-rule cards (reply sha256 `0872680a92d4be3f35994029bdc030f3b48b8d41f07ad0a05f3b158f5d506cfc`, candidate lines sha256 `b65420f07a3c4816d51ac91426ef6025f9055876173828d443e884b1bfdc407b`) [measured]. Notably it judged its blind-fire rate "not causal" and 79% vs 78% multi-move replies as no difference.
3. **Screening (code, committed note `prereg/2026-10-31-causal-screen-note.md` before any screening game).** Each candidate played alone as a one-rule card on 30 fixed cases (seed 4106, first 30 exploratory generated maps), 48 decisions, compared with the existing graded no-card games on the same cases. Keep rule declared before play: mean fitness difference above 0 and the low end of the 95% case interval above -0.05 [hypothesis, a loose screen]. [measured]

| Rule | Exits | Deaths | Fitness difference | Case interval | Result |
|---|---|---|---|---|---|
| r1 | 12 | 13 | +0.101 | -0.113 to +0.334 | dropped |
| r2 | 11 | 15 | -0.034 | -0.276 to +0.202 | dropped |
| r3 | 12 | 16 | +0.155 | -0.049 to +0.358 | kept |
| r4 | 10 | 17 | -0.034 | -0.274 to +0.177 | dropped |
| r5 | 8 | 20 | -0.150 | -0.367 to +0.036 | dropped |
| r6 | 10 | 18 | -0.022 | -0.212 to +0.119 | dropped |

   No-card games on the same 30 cases: 11 exits, 15 deaths, mean fitness 0.063 [measured]. **One of six rules survived** (r3, the path-travel rule). It is a screen on 30 games; its interval includes 0.
4. **Assembly (Spark, one call).** Given only the goal and the surviving rule with its numbers (`~/symbiont-runs/evolve/finalcard`), Spark wrote the final card. Because one rule survived and the card format asks for 3 to 5 rules, **the card is that one rule stated three ways** [measured]. The rule is about using one path-travel command for a distant destination instead of step moves; it is not the "one move per reply" card, although a keyword check flags the wording [measured].

## Hold-out: analysis maps and test maps are disjoint

The goal, the tallies, the screening and the assembly read only the analysis maps (7 Freedoom training maps and the 34 exploratory generated maps OB0101 to OB0136). The test plays 53 other maps: 40 generated and 13 Freedoom held-out, all used earlier by the held-out test. `results/evolve-selfgoal-split.json`; `check` refuses on overlap.

## Claims

- **Primary (C1): whole-game fitness, final card minus no card**, paired by case on the **360 generated-map cases**. Fitness is `symbiont.act1.game_fitness` (1.0 exit, plus 0.5 times furthest route share, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis]).
- **Secondary (C2): exit rate, final card minus no card**, same cases.
- The **65 Freedoom cases** are reported apart and never decide the primary.
- Earlier cards (the self-goal card: fitness tie, exit rate tie on these cases) are reported separately in `results/evolve-confirm-primary.json`.

## Arm and card (exactly as the player receives it after "Lessons from earlier games:")

The **no-card arm is not replayed**: the stored graded no-card games of the held-out test (run `heldout-onemove-none`, 425 games) on exactly these cases.

Final card sha256 `b5d29fe76a4a5fd8a18b1d217e83aead70689fc71fb718cb13738b823eacb5c1`:

```
1. What went wrong: using step moves for distant travel. Instead: use one path travel command to the distant destination. Check: check that the goal is distant before choosing moves.
2. What went wrong: breaking distant travel into separate step moves. Instead: send a single path travel command instead. Check: check that the command reaches the distant destination.
3. What went wrong: stepping manually toward a far destination. Instead: rely on one path travel command. Check: check that step moves are avoided for distant goals.
```

## Comparability of the reused no-card games [measured]

No-card games code commit `4b4d83742cf91ffcfea509647e828bfbc5f9cf59`. `check` refuses unless: the stored identity (model `muse-spark-1.3-contributor`, reasoning low, 32 decisions) equals the card arm's; `src` at HEAD equals that commit's `src` tree; ViZDoom is exactly 1.3.2 and both Freedoom game files match the hashes in the code; every generated map file matches its declared sha256. Same skill 3, no cut moves, API default temperature, 32 decisions for both arms. Disclosed differences: the no-card games were played by the held-out test's runner (through a wrapper that computes would-fire and shows nothing, so the prompt is identical to a game without Evolve), on the 5080 on Oct 29 to 30; the card arm is played by `confirm_test.py` later and on three machines, so a change in the model or API between the two is not balanced.

## Machines and partitions (fixed before play)

The 425 cases in seed-major order are split by case index modulo 9: the 5080 (WSL Ubuntu 24.04, CPU, 16 workers) takes 6 of every 9 (284 cases), the Strix (Linux x86_64, CPU only, 6 workers) takes 2 (94) and the laptop (macOS, 4 workers) takes 1 (47). Each machine has its own state, log and done-file and runs `check` first; a machine whose check fails does not play and its cases are dropped and counted. ViZDoom 1.3.2 on all three. Spark calls go through each machine's own spend ledger (5080 cap 50 dollars, Strix cap 5 dollars counted against the laptop's 30). The scorer merges the three states.

## Cases, decision budget

425 cases: 40 generated maps at 9 seeds (360) and 13 Freedoom maps at 5 seeds (65), seeds 4001 to 4009 and 4001 to 4005. **32 decisions** (the reused games' budget).

## Intervals, decision rules, ties

Two 95% percentile bootstraps of the paired mean difference, 10,000 draws, fixed seed 20261031 [established]: the map interval resamples maps with their cases together, the case interval resamples single cases (`score_final.compare`). A claim reads `better` only if the low ends of BOTH intervals are above 0, `worse` only if both high ends are below 0, otherwise `tie`. **A tie is reported as a tie.** No gate changes after results, no re-slicing, no extra seeds.

## Size, spend, ungraded games

In the held-out test, one move per reply on these maps had a fitness difference of +0.111 over 360 cases [measured]; with a paired SD of about 0.45 [measured], 360 independent cases detect about 0.066 at 80% power [hypothesis]; map clustering widens that. The screening difference of the surviving rule was +0.155 on 30 games with an interval including 0 [measured]. Spend about 425 x 0.0037 = 1.6 dollars [hypothesis, held-out run ledger]. An API or network error, or a reply the server returns empty or without usage, makes a game ungraded and it replays up to 3 times; a reply with content but no parseable move is played as a non-move. A case ungraded after 3 replays is dropped from all arms and counted; more than 10% dropped makes the scorer refuse. Games started, ungraded attempts and drops per arm are published. Runs are detached with a log and done-file and resume from state.

## Disclosures

- The card and its goal are Spark's own wording; we chose the inputs, the screening cases, the keep rule and ran the calls. Fitness is our external judge, never shown to Spark.
- One of six candidates survived a loose 30-game screen with an interval including 0, so selection of the rule is itself noisy; the confirmatory test is what counts.
- The self-card arm of the earlier test (`prereg/2026-10-31-evolve-selfcard-confirm.md`) was paused for capacity during this test and resumed afterwards; its exit-priority arm was dropped before play.
- These maps were already used by the held-out test; no card here was written from them.

## What the pitch may say

Only the sentence `scripts/evolve/confirm_test.py` builds from the numbers. The words "evolved", "self-improving", "learned from its own mistakes" and "recursive" are never used: the card is written by the model from its own stated goal, its causal proposals and a screening we ran, and the pitch says exactly that.

## Results file

`results/evolve-confirm.json`: counts, ids, labels and intervals only (no card text): commits, this file's sha256, card hash, model id, ViZDoom version, cases planned, scored and dropped, games and ungraded attempts per arm, per-arm exits, deaths, alive at the end, kills and fitness, the C1 and C2 comparisons with both intervals, the Freedoom set apart, and the sentence.

## Amendments

None.
