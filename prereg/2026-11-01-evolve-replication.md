# Pre-registration: does the round-1 final card replicate on fresh maps? (Muse Spark plays Freedoom via ViZDoom)

**FROZEN 2026-11-01.** Code pinned at 9066b4b5b5032c9abe612ace5e26ebc0899ff72b (this commit's parent; `scripts/evolve/increment_test.py check` enforces it). Committed alone, before any game of this test was played. An amendment cannot change the arms, card, maps, partitions, seeds, condition, fitness, pairing, bootstrap or decision rule.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## Question

The final card of `prereg/2026-11-01-evolve-final-card-confirm.md` (frozen 5dd9656) read `better` on fitness against the reused no-card games: +0.168 (map interval 0.063 to 0.274) on 360 generated-map cases [measured] (`results/evolve-confirm.json`). Does it replicate when both the card and no card are played together on 40 maps never used anywhere? The card text is unchanged.

## Arms and card

Both arms are played in this test: **none** (no card; the prompt is byte-identical to a game without Evolve) and **final**. Final card sha256 `b5d29fe76a4a5fd8a18b1d217e83aead70689fc71fb718cb13738b823eacb5c1` (exactly as the player receives it after "Lessons from earlier games:"):

```
1. What went wrong: using step moves for distant travel. Instead: use one path travel command to the distant destination. Check: check that the goal is distant before choosing moves.
2. What went wrong: breaking distant travel into separate step moves. Instead: send a single path travel command instead. Check: check that the command reaches the distant destination.
3. What went wrong: stepping manually toward a far destination. Instead: rely on one path travel command. Check: check that step moves are avoided for distant goals.
```

## Maps, cases, condition

Fresh generated maps declared before any play in `prereg/2026-10-31-increment-maps.md` (OB0301 and up, seeds 7301 and up, the first 40 passing the frozen keep rule, `results/evolve-increment-maps.json`); `check` refuses any overlap with the held-out test's maps or the exploratory fresh maps. Seeds 4301 to 4306 on every map: **240 cases, 480 games**, seed-major order, both arms in each batch so a model change falls on both alike. Skill 3, no cut moves, **32 decisions** (as in the confirmed test), Muse Spark `muse-spark-1.3-contributor` at reasoning low, API default temperature.

## Claims, intervals, decision rule

- **Primary: whole-game fitness, final card minus no card**, paired by case (same map, seed, skill). Fitness is `symbiont.act1.game_fitness` (1.0 exit, plus 0.5 times furthest route share, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis]).
- **Secondary: exit rate, final card minus no card.**
- Two 95% percentile bootstraps of the paired mean difference, 10,000 draws, fixed seed 20261031 [established]: the map interval resamples maps with their cases together, the case interval resamples single cases (`score_final.compare`). A claim reads `better` only if the low ends of BOTH intervals are above 0, `worse` only if both high ends are below 0, otherwise `tie`. **A tie is reported as a tie.** No gate changes after results, no re-slicing, no extra seeds.

## Size from the measured noise

The paired standard deviation of fitness was about 0.45 in earlier runs [measured]; 240 independent cases detect a difference of about 2.8 x 0.45 / sqrt(240) = 0.081 at 80% power and 5% [hypothesis]; map clustering widens that. The earlier estimate was +0.168, and as a card chosen after a screen it carries a winner's-curse bias [established], so a smaller true effect is expected.

## Machines, partitions, comparability

The 240 cases in seed-major order are split by case index modulo 9: the 5080 (WSL, CPU, 16 workers) takes 6 of every 9, the Strix (Linux, CPU only, 6 workers) takes 2, the laptop (macOS, 3 workers) takes 1. Each machine has its own state, log and done-file and runs `check` first, which refuses unless ViZDoom is exactly 1.3.2, both Freedoom game files match the hashes in the code, every generated map file matches its declared sha256, the card matches this file and the pinned code is HEAD's; a machine whose check fails does not play and its cases are dropped and counted. Both arms run on all machines under the same settings, so the machines cannot favor one arm. Spark calls go through each machine's own spend ledger; the total Spark cap is 115 dollars after the owner's additions.

## Spend, pace, ungraded games

About 480 x 0.0037 = 1.8 dollars [hypothesis, from the confirmed test's ledger]. About 250 games an hour across the three machines was measured in the confirmed test [measured], so about 2 hours [hypothesis]. An API or network error, or a reply the server returns empty or without usage, makes a game ungraded and it replays up to 3 times; a reply with content but no parseable move is played as a non-move. A case ungraded in either arm after 3 replays is dropped from both and counted; more than 10% dropped makes the scorer refuse. Games started, ungraded attempts and drops per arm are published. Runs are detached with a log and done-file and resume from state.

## Disclosures

- The card was chosen from six candidates by a loose screen on 30 games; this test is its replication, not a new selection.
- The earlier no-card games were played by a different runner on other dates; here both arms are played together by one runner.
- ViZDoom 1.3.2 on all machines; the version is recorded in the results file.

## What the pitch may say

Only the sentence `scripts/evolve/increment_test.py` builds from the numbers. The words "evolved", "self-improving", "learned from its own mistakes" and "recursive" are never used.

## Results file

`results/evolve-replication.json`: counts, ids, labels and intervals only (no card text): commits, this file's sha256, card hash, model id, ViZDoom version, cases planned, scored and dropped, games and ungraded attempts per arm, per-arm exits, deaths, alive at the end, kills and fitness, the primary and secondary comparisons with both intervals, and the sentence.

## Amendments

None.
