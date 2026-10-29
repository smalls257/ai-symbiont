# Pre-registration draft: Evolve, a small paired test of evolved lesson cards (plays Freedoom via ViZDoom)

**DRAFT, not frozen.** The owner-proxy freezes it with a commit that changes only this status line. No held-out game is played before then.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute. Every result row is labeled floor, ceiling, reference or under test, and the no-selection row and the generation-0 row are always printed beside the evolved row.

## Question

Does selecting lesson cards on play, with a language model writing each new card from the best and worst games of the current one, find a card that plays better than a card chosen without selection, when both get the same games and the same seeds?

## Design (run 2, about 200 Spark games)

| Phase | Games | What |
|---|---|---|
| Noise | 25 | the generation-0 best card replayed 5 times on the same 5 cases |
| Evolve | 100 | each arm, 5 generations: the current best card and one child play the same 5 fresh cases (10 games a generation, 50 an arm) |
| Final | 72 | three cards (generation-0 best, no-selection best, evolved best) on the same 24 fresh cases: 12 on selection maps, 12 on held-back maps |

- Every case is fresh: no map-and-seed pair is played twice, across generations or phases, and the run raises if one is reused. Each generation re-scores its current best on that generation's cases only; no fitness is carried over.
- The child is written by Muse Spark (reasoning medium) from the prose of the best and the worst game of the current card (counts and coarse words, no map name or score). A child naming a map, coordinate, door number, monster position or landmark is rejected by the pattern filter or the Spark judge and asked for again, three times at most, else the run stops.
- The selecting arm keeps the card with the better mean on that generation's cases (a tie goes to the shorter card). The no-selection arm gets the same games and the same seeds, writes its children the same way, and keeps one of the two cards by a coin that never looks at a score.
- Players: Muse Spark, reasoning low, temperature 0, normal skill, no cut moves, 16 decisions a game, the card in front of the game prompt. Temperature 0 was the setting in which the three test cards differed most in the card-sensitivity check [measured] (results/evolve-sensitivity.json): the generation-0 best card scored 1.18 within-card standard deviations above the empty card, a strong hand-written card 0.54 and a deliberately bad card 0.54 below. Reasoning medium did not help (0.71, 0.19, 0.01) and the card as system rules helped only the bad card (-0.96) [measured]. Temperature 0 does not make replies deterministic [measured].
- Maps: the 10 maps of the training half that pass the navigation smoke test (MAP01, 02, 05, 06, 09, 10, 11, 14, 29, 31 [measured], results/evolve-levels.json). Validation takes the larger of 3 and a sixth of the passing count, at the middle of equal parts of the list in map order: MAP02, MAP10 and MAP29 are held back and never used in the evolve phase; the other 7 are selection maps. The held-out maps (every fourth map) are never played in this run.

## Claims (all exploratory in run 2, because they use training and validation maps)

| Claim | Test (paired by case) | Label |
|---|---|---|
| C1 (primary) | evolved best minus no-selection best, all 24 final cases | under test |
| C2 | evolved best minus generation-0 best, all 24 final cases | under test |
| C3 | C1 and C2 on the 12 held-back-map cases alone | under test |
| Reference rows | no-selection best minus generation-0 best; the three card means | reference |

The scored repeat of the final test, on the held-out maps that pass the extended navigation test at freeze time and seeds 1001 and 1002, uses the same design and is registered by amending this file before any held-out game is played. The Glimmer transfer claims (a card helps a different model; an adapter trained on the winning lessons) wait for it.

## Noise and the interval width

The first 25 games replay one card on the same cases: one game's variance across replays is 0.117 and its standard deviation 0.342 [measured] (results/evolve-run2.json). A paired difference of two cards over 24 cases, one game each, then has a 95% half-width of 1.96 times the square root of (2 x 0.117 / 24), which is 0.193 [measured]. A difference smaller than that reads as a tie; the generation-0 spread between cards in the first exploratory run was a standard deviation of about 0.023 [measured], so selection among near-identical cards cannot show in 24 games. Per card the sensitivity check saw a gap of 0.3 to 0.6 only between cards that differ a lot (the best generation-0 card against the empty card) [measured].

## What run 2 showed (exploratory, results/evolve-run2.json)

- The final comparison [measured]: evolved best minus no-selection best was -0.001 (95% interval -0.053 to 0.047, a tie); evolved best minus generation-0 best was -0.115 (-0.317 to 0.020, a tie); on the 12 held-back-map cases alone -0.007 and -0.026, both ties.
- The no-selection arm kept its starting card in all 5 generations (a coin; chance 1 in 32 [hypothesis]), so its best card is the generation-0 card. Its final-test games are therefore a replay of the generation-0 card on the same cases, and the difference between the two was -0.114 (-0.321 to -0.006) [measured]: an identical card read as "worse" by a hair, which is what a 95% interval does about once in 20 comparisons and shows the noise is as large as the noise phase said.
- The reflection step [measured]: of 5 children written from the best and worst games in the evolved arm, 3 beat their parent on the same cases (95% Wilson interval 0.23 to 0.88); in the no-selection arm 2 of 5 (0.12 to 0.77); of 5 children by a random operator, 2 (0.12 to 0.77). The mean fitness gain of a child over its parent was -0.09, -0.06 and -0.01. Five children a group cannot tell these apart.
- Cost: 2763 Spark calls and 0.68 dollars for the five runs [measured] (spend ledger).

## Fitness, picking, guards

- Per game: 1.0 for the exit, plus 0.5 times the furthest share of the walking route to the exit reached, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis] (the weights are a judgment call). Kills are reported, never scored. A shot fired with no enemy in view is a wasted move.
- Fitness check on real generation-0 games [measured]: the empty card scored -0.351, stand still -0.620, fire in place -0.915, spin -0.905, so each gaming policy scores below the empty card (results/evolve-gen0.json).
- The final comparison uses only fresh cases, none of which any card was chosen on. The generation-0 best card was chosen in the first exploratory run on other maps and seeds.
- Ungraded games (an API or network error) are played again, up to a limit of 10% of a phase's games [hypothesis] (design setting); beyond it the phase stops. A game is never scored as a loss or a win by default.

## Bootstrap and decision words

Resample maps with replacement, keeping each map's cases together; 10,000 draws, fixed seed; 95% percentile interval [established] (as in earlier preregs). Better if the interval's low end is above 0, worse if its high end is below 0, else tie.

## Known limits and disclosures

- Held-out exposure through navigation development [measured, dates 2026-10-29 PDT]: while the navigation was extended, a scripted walker (go_to to the exit, no model, no card, no lesson store, output only under a temporary directory) was started on all 8 held-out maps (MAP04, 08, 12, 16, 20, 24, 28, 32) in the engine, in batches between about 01:47 and 02:40 including single-map debug runs on MAP04, MAP08 and MAP12. The route verifier has refused held-out maps since it was fixed to call the level guard, and is tested to. See the navigation report (nav-extend-report.md, section on held-out exposure).
- Fixes those runs informed: the pickup-height rule (a skull on a high pedestal on MAP24), solid scenery blocking cells (MAP04), walkover exits crossed rather than pressed (MAP24), thin door slabs and a double door's switch reach (MAP04), checking that a walkover line can really be crossed (MAP24), and wall clearance 12 to 16 (stuck positions on MAP08 and a training map). MAP24 shaped three of them. They are generic geometry rules, but the held-out pass count rose more in proportion (2 to 7 of 8) than the training count (5 to 10 of 24) and so overstates what the extension would show on unseen maps.
- Ruling: both arms share the same navigation, the same fitness and the same games, so this exposure cannot favor the evolved arm over the no-selection arm and does not bias C1 or C2. It can affect which held-out maps pass and how routable they are. Held-out maps remain unplayed by any model or card.
- The smoke test assumes every key is held; three passing training maps (MAP10, MAP11, MAP31) are ones where the scripted walker stalls in the engine.
- Part of the sensitivity check ran before the navigation extension was merged and part after, so its absolute fitness levels are not comparable across settings; its gaps within a setting are.

## Stop rules

- Spend: the ledger raises at the cap; this run stops at 3 dollars in all [established] (owner decision, total cap 15 dollars).
- More than 10% of a phase's games ungraded stops it [hypothesis] (design setting); three rejected children in a row stop an arm.

## Spend

Planning figures [hypothesis]: about 0.005 dollars a game and about 0.9 dollars for the 200 games with the author and the judge.
