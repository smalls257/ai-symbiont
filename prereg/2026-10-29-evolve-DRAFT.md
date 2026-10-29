# Pre-registration draft: Evolve, evolving lesson cards on Freedoom (plays Freedoom via ViZDoom)

**DRAFT, not frozen.** The owner-proxy freezes it with a commit that changes only this status line. No held-out game is played before then.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute. Every result row is labeled floor, ceiling, reference or under test, and the no-selection row and the no-card row are always printed beside the evolved row.

## Question

Does selecting lesson cards on play, with a language model writing the variations, find cards that make a model play better on levels it never saw and under changed conditions, and does it beat the same number of games spent without selection?

## Claims

| Claim | Test (paired by level, seed and condition) | Label |
|---|---|---|
| C1 (primary) | best evolved card minus best no-selection card, Muse Spark playing, all held-out games | under test |
| C2 | the same difference on the harder condition alone (skill 4 and cut moves) | under test |
| C5 | Glimmer with the evolved card minus Glimmer with no card, normal condition | under test |
| C4 | Glimmer with the adapter and no card minus plain Glimmer with the card, normal condition | under test |
| C3 (exploratory) | share of children that beat their parent, adapter-written minus plain-written | exploratory |

Non-goals: general recursive self-improvement; speed-of-learning claims. Anti-goals: a card that memorizes levels; a gain from gaming the score; a cherry-picked clip.

## Arms and labels

| Arm | Player | Label |
|---|---|---|
| No card | Spark | floor |
| Best generation-0 card | Spark | reference |
| Best card of the no-selection arm (same population, same operators, same games, parents chosen at random) | Spark | reference (equal compute) |
| Best evolved card | Spark | under test |
| No card, then best evolved card | Glimmer | floor, then under test |
| Adapter Glimmer, no card | Glimmer | under test |

## Levels

- Held-out levels: the held-out maps (every fourth map of freedoom2, prereg/2026-10-27-act1-level-split.md) that pass the navigation smoke test at freeze time. At the last count 7 of the 8 pass (MAP04, 08, 12, 16, 24, 28, 32 [measured]; results/evolve-levels.json), MAP20 does not. The list is written into the freezing commit with each dropped map and its reason. No model and no card has played a held-out map; MAP24 and MAP32 are not to be played before the freeze.
- Smoke test [measured]: 17 of 32 maps pass the route check after the navigation extension (training 10 of 24, held-out 7 of 8). The check assumes every key is held; three passing training maps (MAP10, MAP11, MAP31) are ones where the scripted walker stalls in the engine.
- Training and validation levels: the 10 passing training maps are MAP01, 02, 05, 06, 09, 10, 11, 14, 29, 31. Validation takes V = the larger of 3 and the passing count divided by 6, rounded down, maps at the middle of V equal parts of the passing list in map order; with 10 maps that is 3 validation maps (MAP02, MAP10, MAP29) and 7 selection maps (MAP01, 05, 06, 09, 11, 14, 31). With all 24 training maps passing the same rule gives 4 validation maps. Validation maps are never used for selection or picking. The earlier exploratory run used held-back seeds on 5 maps as a stand-in; that is weaker, and its results are labeled exploratory.
- Seeds: the final test uses seeds 1001 and 1002 on every passing held-out level, in two conditions: normal (skill 3, no cut moves) and harder (skill 4, 10% of moves cut short) [hypothesis] (design setting).
- Map titles and landmark descriptions in lessons are left to the Spark judge (reasoning medium); the pattern filter catches map numbers, coordinates, sector and door numbers and monster positions only.

## Fitness, picking, guards

- Per game: 1.0 for the exit, plus 0.5 times the furthest share of the walking route to the exit reached, minus 0.02 per tagged mistake, minus 0.5 for dying [hypothesis] (the weights are a judgment call). Kills are reported, never scored. A shot fired with no enemy in view is a wasted move.
- Fitness check on real generation-0 games [measured]: the empty card scored -0.351, stand still -0.620, fire in place -0.915, spin -0.905, so each gaming policy scores below the empty card (results/evolve-gen0.json).
- Picking each arm's card: highest mean training fitness over the last two good generations, among cards with at least 8 graded games in them; validation games are never used. A lesson stays only if the card does at least as well with it as without it on cross-level cases that are no lesson's source level.
- Noise check in generation 0 [measured], from the final graded games (12 card-and-level seed pairs of the three noise cards; results/evolve-gen0.json): one game's variance across seeds 0.0389, the variance of the card means over 8 games 0.0054, so the true spread between cards is about 0.0005 after removing the luck left in an 8-game mean. Selection averaged 4 games per card, where luck is 0.0389 / 4 = 0.0097, above 0.0054: the verdict is DOUBLE_GAMES, and doubling alone does not clear it either. By the same numbers selection needs about 77 games per card before luck falls below the true spread.
- The standard error of a 4-game mean is 0.099 [measured].
- Fresh seeds (owner ruling): every generation selects on cases (level and seed) no earlier generation played, and the run raises if one is reused. Elites and survivors are scored again on the new generation's cases only; no fitness is carried over. The gap each generation is the fitness of the card selection favored going in (best on the previous generation's cases), on this generation's fresh cases, minus its fitness on the held-back seeds: neither number is chosen on the games it is scored on.
- Gap rule: the training-minus-validation gap rising by more than that standard error (0.099 [measured]) two generations in a row stops evolution and keeps the last good generation.

## Bootstrap and decision words

Resample held-out levels with replacement, keeping each level's games together; 10,000 draws, fixed seed; 95% percentile interval [established] (as in earlier preregs). Better if the interval's low end is above 0, worse if its high end is below 0, else tie. C4 holds if the low end is above minus the standard error of a held-out arm mean (0.099 [measured], from generation 0).

## Expected interval width

From generation-0 seed noise (variance 0.0389 per game [measured]): a level mean over 4 games has variance 0.0097 and the difference of two arms on one level 0.0195, a standard deviation of 0.140 [hypothesis]; over 8 levels the standard error is 0.049 and the 95% half-width about 0.097 [hypothesis], ignoring card-by-level interaction. The true spread between cards in generation 0 is a standard deviation of about 0.023 [measured], far below that width: unless evolution produces differences several times larger than the generation-0 spread, C1 reads as a tie.

## Exploratory evidence before this draft

Generations 1 to 3 on the five maps that passed the first smoke test were run with selection at 1 game per case, while the corrected noise verdict for that setting is DOUBLE_GAMES, so their comparison of the evolved arm with the no-selection arm is not interpretable and carries that label (results/evolve-generations.json). They show that the loop runs end to end, not that selection works. A run that is to count needs the games per card the noise check asks for, or a different way to cut the noise (more levels and seeds per generation, or cards compared on paired cases only).

## Before and after clip

The first passing held-out level in map order, seed 1001, normal condition, no-card arm against the best evolved card, Spark playing. Chosen by this rule before any held-out game; the level is named in the freezing commit.

## Known limits and disclosures

- Held-out exposure through navigation development [measured, dates 2026-10-29 PDT]: while the navigation was extended, a scripted walker (go_to to the exit, no model, no card, no lesson store, output only under a temporary directory) was started on all 8 held-out maps (MAP04, 08, 12, 16, 20, 24, 28, 32) in the engine, in batches between about 01:47 and 02:40 including single-map debug runs on MAP04, MAP08 and MAP12. The route verifier has refused held-out maps since it was fixed to call the level guard, and is tested to. See the navigation report (nav-extend-report.md, section on held-out exposure).
- Fixes those runs informed: the pickup-height rule (a skull on a high pedestal on MAP24), solid scenery blocking cells (MAP04), walkover exits crossed rather than pressed (MAP24), thin door slabs and a double door's switch reach (MAP04), checking that a walkover line can really be crossed (MAP24), and wall clearance 12 to 16 (stuck positions on MAP08 and a training map). MAP24 shaped three of them. They are generic geometry rules, but the held-out pass count rose more in proportion (2 to 7 of 8) than the training count (5 to 10 of 24) and so overstates what the extension would show on unseen maps.
- Ruling: both arms share the same navigation, the same fitness and the same games, so this exposure cannot favor the evolved arm over the no-selection arm and does not bias C1 or C2. It can affect which held-out maps pass and how routable they are, so the held-out list is reported with this disclosure. Cost if wrong: the claim that the held-out maps were unseen by the experiment holds for models and cards only, not for the navigation code.

## Stop rules

- Spend cap: the ledger raises at the cap and the run stops and reports [established] (owner decision, total cap 15 dollars).
- More than 10% of a generation's games ungraded stops the run [hypothesis] (design setting); an ungraded game is played again on resume, never scored as a loss or a win.
- Generality rejections above half of a generation's children stop the run until the mutation prompt is fixed.
- The gap rule above; the noise verdict above.

## Spend

Planning figures [hypothesis]: about 0.25 dollars for generation 0 and the checks [measured], about 0.3 dollars per evolution generation at 1 game per case (more at the 77 games per card the noise check asks for), about 1 dollar for the Spark final test, and Glimmer arms and the adapter on local hardware.
