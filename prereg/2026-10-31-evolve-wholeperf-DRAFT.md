# Pre-registration: does "one move per reply" improve performance as a whole? (Muse Spark plays Freedoom via ViZDoom)

**DRAFT, not frozen.** Frozen by a commit that changes only this header and fills "Code pinned at <sha>" with its parent. Code pinned at: (filled by the freeze).

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## Question

Does telling Muse Spark to send exactly one move per reply improve what happens in the game, in the owner's priority order: first reaching the exit, then surviving, then killing monsters, on fresh generated maps no run has used?

## Primary: hierarchical pairwise comparison (generalized pairwise comparison) [established]

For each paired case (same map, same seed, same skill), compare the one_move game with the none game, tier by tier, and stop at the first tier that differs:

1. Exit: reaching the exit beats not reaching it.
2. Death: if exit is tied, surviving beats dying.
3. Kills: if still tied, more kills beats fewer.
4. Otherwise the pair is a tie.

Each case is a win (one_move better), a loss or a tie. **Net benefit = P(win) - P(loss)**; the win ratio = wins / losses is reported beside it. Both are published with the count of pairs decided at each tier.

Intervals (10,000 draws, fixed seed 20261031 [established]): the **map interval** resamples maps with their cases together (the primary gate); the **case interval** resamples single cases. Word: `better` only if the low ends of BOTH intervals are above 0; `worse` only if both high ends are below 0; otherwise `tie`. A tie is reported as a tie.

## Secondaries (each reported alone, never combined, never decisive)

Exit rate, death rate (died without exiting), alive-at-the-end rate, mean kills, mean whole-game fitness (1.0 exit, plus 0.5 times furthest route share, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis]); each as the paired difference with both intervals, plus the per-tier decided counts.

## What the exploration found (not scored) [measured]

On 34 fresh generated maps (OB0101 to OB0136 passing; declaration `prereg/2026-10-30-fresh-maps.md`), 80 paired cases, 48 decisions, Muse Spark, none against one_move:

- Exits 34 of 80 with none, 27 of 80 with one_move. Deaths 33 and 27. Alive at the end 13 and 26. Mean kills 4.81 and 4.19. Mean fitness 0.130 and 0.222 (difference +0.091, standard error 0.079).
- The same pairs under this hierarchy: 24 wins, 29 losses, 27 ties; net benefit -0.062, win ratio 0.83; map-clustered interval -0.26 to +0.15 (this run is exploratory and not scored).
- Pairs decided at the exit tier 9, at death 11, at kills 33. **In practice the primary is mostly a kills comparison**, because a kills difference is the commonest first difference. That follows the owner's priority order and is stated here so no one reads the primary as "exits".
- The earlier whole-game fitness gain of "one move per reply" (+0.17 on training maps) came through route progress and fewer mistakes, not through more exits; at 48 decisions it did not raise exits. Expect `tie` or `worse` on the primary; the test can detect a harm as well as a gain.

## Arms and decision budget

Two arms on every case: none (no card) and one_move (the card quoted in `prereg/2026-11-01-evolve-heldout.md`, sha256 `1f103cea606a48e069b660063c42818c8441e0a97fadd34da583056e3e4268ba`). **Both play 48 decisions.** Why 48: the exit tier needs exits to exist; at 48 decisions none exited in 34 of 80 games (43%) [measured], against about a third at 32 decisions in the depth check, and the depth check found no further gain from 48 to 64 on training maps (fitness change -0.001) [measured]. A larger budget would raise the exit rate for both arms and shrink the exit-decided share further; a smaller one would leave the exit tier empty.

## Maps and cases

Fresh generated maps, declared before any play in `prereg/2026-10-31-wp-maps.md`: OBLIGE seeds 7201 and up (ids OB0201 and up), the same recipe, settings and keep rule as `prereg/2026-10-29-generated-maps.md` (walker and route-check code at 852583c). The first 50 passing maps in id order are kept. Never the 34 exploratory maps, the 40 maps of the held-out test, or any Freedoom map. Seeds 4201 to 4206 on every map (6 each): 300 cases, 600 games. Skill 3, no cut moves, Muse Spark `muse-spark-1.3-contributor` at reasoning low, API default temperature. Whole-case batches of 8, both arms in each batch, seed-major order.

## Size from the measured noise

The per-case outcome (+1, 0, -1) had a standard deviation of 0.81 over the 80 exploratory pairs [measured]. Treating cases as independent, 300 cases detect a net benefit of about 2.8 x 0.81 / sqrt(300) = 0.13 at 80% power and 5% [hypothesis]; clustering by map widens that (the between-map spread of this outcome is not measured; with 50 maps and 6 cases each a modest design effect is expected). The exploratory point estimate (-0.06) is smaller than the detectable effect, so a `tie` is the likely reading; the test is sized to tell a gain or loss of about 0.13 or more.

## Ungraded games, drops, order

An API or network error, or a reply the server returns empty or without usage, makes a game ungraded and it replays up to 3 times; a reply with content but no parseable move is played as a non-move. A case ungraded in either arm after 3 replays is dropped from both and counted; more than 10% dropped makes the scorer refuse (raise), reported as incomplete. The results file publishes games started, ungraded attempts and drops per arm. [hypothesis]

## Run, spend, stop rules

- On the 5080 CPU, detached (`setsid nohup`, log, done-file), resuming from per-arm state. Workers start at 4 and are cut (to 2) if the Core D2 containers sharing the machine slow by more than about 10%; the worker count is an operational choice, disclosed, never a design change. The ViZDoom version is the 5080's and is recorded in the results file; both arms run on it. [hypothesis]
- Spend: 600 games at about $0.0055 each is about $3.3 [hypothesis from the exploratory run]; this run's cap is 10 dollars, the 5080 ledger cap is 50. A hash, code or map-file mismatch stops the run. [hypothesis]
- No gate changes after results, no re-slicing by map or seed, no extra seeds.

## Disclosures

- The card was written by us after reading a depth check; it is a prompt instruction, not something the model learned. It was the best of seven cards on training maps, so its earlier fitness estimate carries winner's-curse bias [established].
- This test was added after the held-out test (`prereg/2026-11-01-evolve-heldout.md`) was frozen, and after the exploratory 48-decision look above. The held-out test's results are reported separately and neither overrides the other.
- Kills are counted by the engine's own counter; a game that ends early has fewer kills.

## What the pitch may say

Only the sentence the scorer builds from the numbers: net benefit with both intervals, the per-tier counts and the word. The words "evolved", "self-improving", "learned from its own mistakes" and "recursive" are never used.

## Results file

`results/evolve-wholeperf.json`: counts, ids, labels and intervals only (no card text): commits, this file's sha256, model id, ViZDoom version, cases planned, scored and dropped, games and ungraded attempts per arm, spend, net benefit, win ratio, per-tier counts, secondaries with both intervals, per-map net benefit, and the sentence.

## Amendments

None.
