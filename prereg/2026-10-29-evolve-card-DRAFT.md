# Pre-registration draft: does the mined lesson card help Muse Spark on maps it never saw? (plays Freedoom via ViZDoom)

**DRAFT, not frozen.** The owner-proxy freezes it with a commit that changes only this status line. The scored runner (`--scored`) refuses to start unless this file is committed, unchanged and frozen, and checks the two card hashes below before the first game. No held-out game is played before then.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute. Every result row is labeled floor, ceiling, reference or under test.

## Question

Does a short card of lessons put in front of the game prompt make Muse Spark play better on held-out Freedoom maps than playing with no card, and how does it compare with a hand-written strategy card?

## The frozen cards

The exact text of each card, as the player receives it after the heading "Lessons from earlier games:", and the sha256 of that text.

Mined card (the best of the six generation-0 cards; sha256 `5984390e1d7cb0afa433857ea8bc8b633f095a2c1f0020bed536a04a26616b15`; the first 12 hex digits are its card id `5984390e1d7c`):

```
1. What went wrong: Moves that changed nothing. Instead: Pick a move that goes somewhere or changes something. Check: Turn toward a side the Layout line calls open; a turn that ends facing the same way wastes a decision.
2. What went wrong: Turning in a room already scanned. Instead: Head for an exit, door or key instead. Check: Do not turn to look around a room you already scanned; pick a door, key or exit from 'Reachable with go_to' instead.
```

Strong hand-written card (sha256 `7cf218224ac841b0fba2cfee32de054e3305642d8e3f6e637ac8954a3d78d14b`, card id `7cf218224ac8`):

```
1. What went wrong: Wandering without a target. Instead: Go to the nearest unexplored door with go_to(door) and open it. Check: Does 'Reachable with go_to' list a door you have not used yet?.
2. What went wrong: Walking back into rooms already checked. Instead: Never re-enter a room you already checked; pick a door you have not used. Check: Have you been in this room before?.
3. What went wrong: Missing the exit. Instead: When an exit sign is in view or listed, head for it with go_to(exit) at once. Check: Does the observation list an exit?.
```

The empty card is no card: the game prompt is byte-identical to a game played without Evolve.

## Arms and claims

| Arm | Card | Label |
|---|---|---|
| no card | none | floor |
| mined | the mined card | under test |
| strong | the strong hand-written card | reference |

| Claim | Paired measure | Label |
|---|---|---|
| C1 (primary) | mined minus no card | under test |
| C2 | mined minus strong | under test |
| C3 | strong minus no card | reference |

All three arms play exactly the same cases: the same map, seed, skill and cut setting, so each case gives three games and three paired differences.

## Cases

- Maps: the 7 held-out maps that pass the navigation smoke test, MAP04, MAP08, MAP12, MAP16, MAP24, MAP28 and MAP32 [measured] (results/evolve-levels.json). The eighth held-out map, MAP20, does not pass. The list is the file's list at the freezing commit.
- Seeds: 2001 to 2014 on every map, 14 seeds, so 98 cases and 294 games [hypothesis] (design setting). No model, card or lesson store has played a held-out map before this test.
- Condition: skill 3, no cut moves, 16 decisions a game, Muse Spark at reasoning low and temperature 0 (the setting in which cards differed most in the card-sensitivity check [measured], results/evolve-sensitivity.json), the card in front of the game prompt.
- An ungraded game (an API or network error) is played again up to the limit below; a game is never scored as a win or a loss by default.

## Fitness and the paired measure

- Per game: 1.0 for the exit, plus 0.5 times the furthest share of the walking route to the exit reached, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis] (the weights are a judgment call; gaming policies score below the empty card [measured], results/evolve-gen0.json). Kills are reported, never scored.
- The paired measure of a comparison is the mean over the 98 cases of (fitness of the first arm minus fitness of the second arm) on the same case.
- Interval: the primary interval resamples maps with replacement, keeping each map's 14 cases together, 10,000 draws, fixed seed 20261029, 95% percentile [established] (as in earlier preregs). Maps are the unit because cases on one map share its geometry and the claim is about maps the model has not seen. A second interval resamples cases and is reported beside it; the decision uses the map interval.

## The bar

- Decision words from the map interval: better if its low end is above 0, worse if its high end is below 0, else tie.
- C1 counts as support for the card only if the word is better and the mean difference is at least 0.10 [hypothesis] (about 0.3 of the replay standard deviation, a size a player would notice). A better word below 0.10 is reported as better but small; a tie is reported as a tie, whatever the mean.
- Report all three claims whatever they say. A result in which the mined card is worse than no card is a result.

## Expected interval width, from the measured noise

One game replayed on the same case has variance 0.117 and standard deviation 0.342 [measured] (results/evolve-run2.json, 25 games). The difference of two arms on one case therefore has variance at least 0.234 [measured]. Over 98 cases the case-level standard error is 0.049 and the 95% half-width 0.096 [hypothesis]. The map-level interval is wider by the spread of the card's effect across the 7 maps, which the replay noise does not measure; I expect it to be at least this wide and cannot state it in advance. A true difference under about 0.1 will read as a tie.

## Known limits

- The card was picked after looking: it was the best of six generation-0 cards on 4 games each in a first exploratory run [measured], and the card-sensitivity check then saw it 1.18 within-card standard deviations above no card at temperature 0 on MAP01 and MAP05, training maps [measured]. Both looks reward luck, so expect shrinkage: its true effect on held-out maps is probably smaller than those numbers. In run 2 the same card, replayed on 24 fresh cases, scored 0.114 below its first play on them, and the evolved card scored 0.115 below that first play [measured] (results/evolve-run2.json): replay noise as large as the differences under study.
- The mined card is two lessons built from the tagger's own check texts; it is not a card a model learned from its own mistakes.
- Held-out exposure through navigation development [measured, dates 2026-10-29 PDT]: while the navigation was extended, a scripted walker (go_to to the exit, no model, no card, no lesson store, output only under a temporary directory) was started on all 8 held-out maps (MAP04, 08, 12, 16, 20, 24, 28, 32) in the engine, in batches between about 01:47 and 02:40 including single-map debug runs on MAP04, MAP08 and MAP12. The route verifier has refused held-out maps since it was fixed to call the level guard, and is tested to. See the navigation report (nav-extend-report.md, section on held-out exposure).
- Fixes those runs informed: the pickup-height rule (a skull on a high pedestal on MAP24), solid scenery blocking cells (MAP04), walkover exits crossed rather than pressed (MAP24), thin door slabs and a double door's switch reach (MAP04), checking that a walkover line can really be crossed (MAP24), and wall clearance 12 to 16 (stuck positions on MAP08 and a training map). MAP24 shaped three of them. They are generic geometry rules, but the held-out pass count rose more in proportion (2 to 7 of 8) than the training count (5 to 10 of 24) and so overstates what the extension would show on unseen maps.
- Ruling: all three arms share the same navigation, the same fitness and the same cases, so this exposure cannot favor one arm over another and does not bias C1, C2 or C3. It can affect which held-out maps pass and how routable they are. No model and no card has played a held-out map.
- The smoke test assumes every key is held; a map where the player cannot fetch a needed key lowers every arm alike.

## The demo clips (named in advance)

The clips are the first three held-out maps in map order, MAP04, MAP08 and MAP12, at seed 2001, normal condition, no card against the mined card, Muse Spark playing, shown whatever the games turn out to be. A reel of the three follows the side-by-side clips. The games are the scored test's own games, recorded; no clip is chosen after the results.

## Stop rules and spend

- Spend: the ledger raises at its cap and the run stops and reports [established] (owner decision); the test is planned at about 1.5 dollars [hypothesis] (294 games at about 0.005 dollars a game, measured in run 2).
- More than 10% of the games ungraded stops the run [hypothesis] (design setting); ungraded games are played again before that count is made.
- The runner stops, reports and does not continue if a card hash differs from the one above.
