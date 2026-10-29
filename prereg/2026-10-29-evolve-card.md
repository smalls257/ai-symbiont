# Pre-registration: does a two-lesson card help Muse Spark on held-out Freedoom maps? (plays Freedoom via ViZDoom)

**FROZEN 2026-10-29.** Code pinned at 6d1ca3859c812fd05821bb9c4cae3b0a1c845c09 (this commit's parent; `final_test.py check` enforces it). Committed alone, before any game on a held-out map exists. An amendment cannot change cards, maps, seeds, condition, fitness, pairing, bootstrap or decision rule. Owner-proxy rulings applied: `.superpowers/rulings/2026-10-29-evolve-card.md`. This file supersedes the wider `prereg/2026-10-29-evolve-DRAFT.md` for the Spark arms (that draft covers run 2, exploratory, on training maps only).

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute. Every result row is labeled floor, ceiling, reference or under test.

The runner is `scripts/evolve/final_test.py` (`check`, then `run --scored`), the scorer `scripts/evolve/score_final.py`, the cards `scripts/evolve/frozen_cards.py`, the results `results/evolve-card.json`. `check` refuses unless this file is frozen and committed alone, its parent is the pinned code commit, `scripts/evolve` and `src` at HEAD equal that commit's trees with nothing uncommitted or untracked, both cards' text and sha256 below match the code, every case is on one of the seven named maps and no map-and-seed repeats. A refusal is raised, never labeled.

## Question

Does a short card of lessons put in front of the game prompt make Muse Spark play better on held-out Freedoom maps than playing with no card, and how does it compare with a hand-written strategy card?

## The frozen cards

The exact text of each card, as the player receives it after the heading "Lessons from earlier games:", and the sha256 of that text. The hash is of `Card.render()` as shown, with no trailing newline.

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

The empty card is no card: the game prompt is byte-identical to a game played without Evolve. The mined card is two lessons whose checks are the miner's own lesson texts for the two most common mistakes in Glimmer's starting point (moves that changed nothing, rooms checked again [measured]); it is not a card a model learned from its own mistakes.

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

All three arms play exactly the same cases: the same map, seed, skill and cut setting, so each case gives three games and three paired differences. Only C1 decides the claim; C2 and C3 are reported with words but never change the C1 verdict.

## Cases and condition

- Maps: the 7 held-out maps that pass the navigation smoke test, MAP04, MAP08, MAP12, MAP16, MAP24, MAP28 and MAP32 [measured] (results/evolve-levels.json). The eighth, MAP20, does not pass. The runner refuses any other map.
- Seeds: 2001 to 2014 on every map, 14 seeds, so 98 cases and 294 games (design setting, not a measurement). No (map, seed) repeats and no model or card has played any of these maps [measured: the level guard refuses a held-out map without a frozen prereg, and its tests].
- Condition: skill 3, no cut moves, 16 decisions a game, Muse Spark (`muse-spark-1.3-contributor`) at reasoning low and temperature 0, the card in front of the game prompt. This is the setting of the card-sensitivity check in which this card's gap over no card was largest [measured] (results/evolve-sensitivity.json; see the three looks below).
- Temperature 0 does not make Spark deterministic: the same card on the same case scored with a standard deviation of 0.342 over 5 replicates [measured, run 2]. Replay noise enters at every decision (server-side sampling, batching, model updates) and at the engine (ViZDoom at a fixed seed is deterministic; the model's reply is not). Spark model updates during the run are not detectable, so the results file records the model id string and the dates of the first and last game.
- Order of play: arms are interleaved within each case (no card, mined, strong on case 1, then case 2, and so on, in batches of whole cases), so a model change in the middle of the run falls on all three arms of a case alike. The runner enforces the order.

## Ungraded games

An ungraded game (an API or network error) is replayed at most 3 times on the same case. A case still ungraded in any arm is dropped from all three arms, so pairing stays complete, and counted. More than 10% of the cases dropped (10 of 98) stops the run, and the result is reported as incomplete, never scored [hypothesis] (design setting). A resume replays ungraded games and never replays a graded game. Spark privacy refusals and the spend cap are not ungraded: they stop the run.

## Fitness and the paired measure

- Per game: 1.0 for the exit, plus 0.5 times the furthest share of the walking route to the exit reached, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis] (the weights are a judgment call; gaming policies score below the empty card [measured], results/evolve-gen0.json). Kills are reported, never scored.
- The paired measure of a comparison is the mean over the cases of (fitness of the first arm minus fitness of the second arm) on the same case.
- Two intervals, both 95% percentile bootstraps with 10,000 draws and fixed seed 20261029 [established] (as in earlier preregs): the map interval resamples maps with replacement, keeping each map's 14 cases together; the case interval resamples single cases. The results file publishes both, and the per-map mean difference of every claim (7 numbers each).

## The decision

- A claim reads `better` only if the low end of the map interval AND the low end of the case interval are above 0; `worse` only if both high ends are below 0; otherwise `tie`. A percentile bootstrap over 7 maps under-covers [established], and the case interval ignores correlation within a map, so both must agree. With 7 maps, a true gain that holds on 5 maps and reverses on 2 will likely read `tie`; that is the bet.
- C1 supports the card only if it reads `better` and the mean difference is at least 0.10 [hypothesis]. A `better` below 0.10 is reported as better but small. A `tie` is reported as a tie; at a mean of 0.05 to 0.10 it is reported as "no measurable gain at this size", never as a trend.
- Multiplicity: three paired comparisons, each with a map interval and a case interval at 95% and no correction, six intervals in all [established]. Only C1 decides.

## Expected width, from the measured noise

One game replayed on the same case has variance 0.117 and standard deviation 0.342 [measured] (results/evolve-run2.json); this rests on 5 cases with 5 replicates each, 20 degrees of freedom, so it is itself rough [hypothesis]. The difference of two arms on one case has variance at least 0.234, so over 98 cases the case-level standard error is 0.049 and the 95% half-width 0.096 [hypothesis]. The map-level interval is wider by the spread of the effect across the 7 maps, which the replay noise does not measure. A `better` with a mean of at least 0.10 therefore needs a true effect of roughly 0.20 or more, about 0.6 replay standard deviations [hypothesis]. The sensitivity gap of 0.61 for this card on two training maps would have to shrink by about two thirds before this test reads `tie`. The owner expects a shrunken effect and a `tie` or a small `better` for C1 [hypothesis].

## Three looks at the card: expect shrinkage

The card was picked after looking, three times, and each look rewards luck:

1. It was the best of six generation-0 cards on 4 games each [measured] (results/evolve-gen0.json).
2. Temperature 0 with reasoning low was chosen because it was the setting, of four tried, in which this card's gap over no card was largest: +0.61, 1.18 within-card standard deviations, against +0.06 (0.13 standard deviations) with the card as system rules and +0.30 (0.56) at the current setting, on MAP01 and MAP05, training maps [measured] (results/evolve-sensitivity.json).
3. In run 2 the same card, replayed on 24 fresh cases, scored 0.114 below its first play, and the evolved card scored 0.115 below that first play [measured] (results/evolve-run2.json): replay noise as large as the differences under study.

At temperature 0 the strong card scored below the mined card (0.14 against 0.47) and above it at two of the four settings (the current one and the system-rules one) [measured]. C2 is therefore expected to read `worse` or `tie` for the mined card [hypothesis].

## Known limits and disclosures

- Held-out exposure through navigation development (facts in `docs/results/2026-10-29-nav-held-out-exposure.md`): a scripted walker with no model, no card and no lesson store was run in the engine on all 8 held-out maps while the navigation was extended, and its traces shaped fixes, MAP24 three of them, MAP04 two or three, MAP08 one. The held-out pass count (7 of 8) is therefore not evidence that the navigation generalizes, and the 7 maps are the routable subset of the held-out 8, within a pool in which 15 of 32 maps fail the route check [measured]. A result covers routable Freedoom maps only.
- Ruling: all three arms share the same navigation, the same fitness and the same cases, so this exposure cannot favor one arm over another and does not bias C1, C2 or C3.
- The smoke test assumes every key is held; a map where the player cannot fetch a needed key lowers every arm alike.
- The seeds, the 98 cases, the bar of 0.10 and the drop limit are design settings, not measurements.

## What the pitch may say

"The card helps" is claimed only if C1 reads `better` with a mean of at least 0.10 under the decision above. The sentence is built in code (`score_final.verdict_sentence`) and written to the results file: "A two-lesson card whose checks are the miner's own texts for the two most common mistakes raised Muse Spark's fitness by X (map interval L to H, case interval L to H) on 7 Freedoom maps no model or card had played, against Y for a hand-written card." Anything less reads "A mined card did not measurably beat no card at this size", with the intervals. The words "evolved", "self-improving", "learned from its own mistakes" and "recursive" are never used for this card test: run 2 showed the evolved card tied or trailed this card [measured], and this card is the miner's check texts, not lessons a model learned.

## The demo clips (named in advance)

The clips are the first three held-out maps in map order, MAP04, MAP08 and MAP12, at seed 2001, normal condition, no card against the mined card, Muse Spark playing, shown whatever the games turn out to be. The strong-card game on the same three cases is also recorded and may be shown. A reel of the three follows the side-by-side clips. The games are the scored test's own games, recorded. If a named clip's game is ungraded after 3 replays, the clip is the next seed (2002) on the same map and the swap is written in the results file. No other substitution.

## Results file

`results/evolve-card.json` holds counts, ids, labels and intervals only, never card text (the hash stands for it). It records `code_commit`, `freeze_commit`, the pinned commit, the sha256 of this file and of both cards, the model id, the dates of the first and last game, the cases planned, scored and dropped, the spend ledger's calls and dollars, the three claims with both intervals and the per-map differences, and the sentence. Every row is labeled floor, reference or under test, and the no-card row is always printed beside the mined row.

## Stop rules and spend

- The ledger cap is 15 dollars in all and raises at the cap, and the run stops and reports [established] (owner decision; this run's own cap is 3 dollars). Planned spend is about 1.5 dollars for 294 games at about 0.005 dollars a game [hypothesis] (run 2), plus replays of at most 10% more, so about 1.95 dollars at worst.
- The runner stops, reports and does not continue if a card hash differs from the one above or the code differs from the pin.

## Amendments

None.
