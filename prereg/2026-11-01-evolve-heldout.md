# Pre-registration: situational lessons and "one move per reply" on held-out maps (Muse Spark plays Freedoom via ViZDoom)

**FROZEN 2026-10-29.** Code pinned at 4b4d83742cf91ffcfea509647e828bfbc5f9cf59 (this commit's parent; `scripts/evolve/held_out_test.py check` enforces it). Re-frozen after the first freeze (6ded1d8): the launch of the first freeze found a missing argument in the runner's run path and stopped before any game was played; the fix is the pinned commit and nothing else changed. Committed alone, before any game on a held-out or generated map was played by a model. An amendment cannot change arms, cards, lessons, cutoff, maps, seeds, condition, fitness, pairing, bootstrap or decision rule.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute. Every result row is labeled floor, reference or under test.

## Questions

1. **C1 (primary).** At the decisions where a situational lesson would fire, does showing it change Muse Spark's play on maps no lesson was mined from, compared with showing nothing?
2. **C2 (second pre-registered claim).** Over the whole game, does "send exactly one move per reply" beat no lesson on those maps?

Whole-game fitness of the situational arm against no lesson is a secondary, reported, never a headline.

## Where the claims came from (exploration, not scored) [measured]

- Situational lessons: whole-game fitness +0.002 over no lesson on the first check (training maps, old cutoff 0.969), where they fired only on maps they were mined from. A new cutoff 0.818 (about 1 decision in 5 on the validation maps' no-lesson decisions) was then tested on fresh seeds 960001 to 960018 of three validation maps (MAP02, MAP10, MAP29), 18 cases per arm, paired. Results, stated plainly:
  - Fire rate: 34 of 224 decisions (15%); 11 of 18 games had at least one fire (MAP02 23 of 107, MAP29 11 of 85, MAP10 0 of 32). Lessons do fire on seeds they were not mined on, and unevenly by map. [measured]
  - At the fired decisions (9 cases with a fire in both arms): mistakes per fired decision 0.14 with lessons against 0.77 with none (difference -0.63, standard error 0.19); route progress over the next 3 decisions -360 against -43 route units (difference -317, standard error 142; on the first fire only: -0.56 mistakes, -267 units, SE 273). **The signs conflict: fewer tagged mistakes, less progress.** Nine cases on two maps cannot say which is real.
  - Whole game: fitness +0.011 (standard error 0.049), route share +0.081 (standard error 0.038).
  - Reading: situational lessons are not dropped, because they fire and the mistake measure moves; they are not claimed either. The prereg below makes the conflict itself the test: C1 is supported only if mistakes improve AND progress does not read worse, which means the progress interval is not wholly below 0; a real progress loss smaller than about 170 units can therefore still read supported. Per the owner's timebox rule ("no sign: stop"), if C1 reads tie or worse, situational lessons are dropped from the pitch and "one move per reply" (C2) becomes the headline.
- One move per reply: +0.167 (standard error 0.069) on 42 training cases, +0.177 (standard error 0.075) on fresh validation seeds, whole game; 69% of tagged mistakes came from the follow-on moves of multi-move replies (results/evolve-depth.json, results/evolve-traces.json). It was the best of seven non-empty cards, so its estimate carries winner's-curse bias [established]: expect a smaller effect. The card was written by us after reading the depth check; the pitch says so.
- The card test already ran (prereg/2026-10-29-evolve-card.md, results/evolve-card.json): a mined card and a hand-written card tied with no card on 98 held-out Freedoom 2 cases. That is reported and stands.

## Arms (all play every case; same map, seed, skill)

| Arm | Card in front of the prompt | Situational lesson when the ranker would fire | Label |
|---|---|---|---|
| none | none (prompt byte-identical to a game without Evolve) | computed and recorded, shown never | floor |
| one_move | the card below | computed and recorded, shown never | under test (C2) |
| lessons | none | top 1 or 2 lessons shown, "use one only if it applies" | under test (C1) |

Card, exactly as the player receives it after "Lessons from earlier games:". One-move card sha256 `1f103cea606a48e069b660063c42818c8441e0a97fadd34da583056e3e4268ba`:

```
1. What went wrong: Sending several moves in one reply. Instead: Send exactly one move per reply and read what happened before the next one. Check: Does your reply hold more than one line? Cut it to the single best move.
```

Situational lessons: lessons file sha256 `2efd1661b33f5c013f23d49737a61254d80baf811a3dbbe0a310ca01ae96b787` (114 lessons Spark wrote from its own paired games on training maps MAP01, MAP05, MAP06, MAP09, MAP11, MAP14, MAP31; the file is not committed, the hash is). It is the 115-lesson file of the exploratory checks **minus the one lesson that restates "one move per reply"**, so C1 and C2 test different content. Cutoff `0.818`: ranker score at which a lesson would fire (design setting: chosen to fire at about 1 decision in 5; tuned on the no-lesson decisions of the validation maps MAP02, MAP10, MAP29, and tested on fresh seeds there, not tuned on any scored case). The cutoff was tuned with the one-move lesson in the file; removing it can shift the fire rate, which is measured and reported, not corrected.

**"Fires" is one rule in every arm.** A decision "would fire" when the ranker's top score for that arm's own observation at that decision reaches the cutoff. The none and one_move arms compute it and show nothing. Trajectories diverge between arms, so each arm's would-fire set is its own.

## Cases, condition, order

- Generated maps (primary set): the 40 kept OBLIGE maps listed under `kept` in `results/evolve-generated-maps.json`, recipe and file hashes declared before any play in `prereg/2026-10-29-generated-maps.md`; 9 seeds each (4001 to 4009), 360 cases. Walker and route-check code are frozen as of commit 852583c; no model played them; the scripted walker ran once on each, for the keep rule.
- Freedoom held-out maps (reported separately): Freedoom 2 MAP04, MAP08, MAP12, MAP16, MAP24, MAP28, MAP32 and Freedoom 1 E1M4, E2M3, E2M7, E3M6, E4M1, E4M5 (13 maps passing the smoke test; results/evolve-levels.json, results/evolve-levels-phase1.json); 5 seeds each (4001 to 4005), 65 cases. Exposure facts: `docs/results/2026-10-29-nav-held-out-exposure.md` (a scripted walker without a model ran on the Freedoom 2 held-out maps while navigation was extended; the earlier card test played those maps with other cards, seeds 2001 to 2014). Seeds here are new.
- 425 cases, 1,275 games. Skill 3, no cut moves, 32 decisions, Muse Spark `muse-spark-1.3-contributor` at reasoning low, API default temperature (the setting of every exploratory game). Whole-case batches of 8, all three arms in each batch, so a model update falls on every arm alike. Ungraded games (API or network error) replay up to 3 times; a case still ungraded in any arm is dropped from all arms and counted; more than 10% dropped makes the scorer refuse (raise) at scoring time, reported as incomplete, never scored; the run itself continues. Privacy refusals and the spend cap are not ungraded: they stop the run. [hypothesis]
- The run is on the 5080 (WSL, detached, 6 game processes; the laptop serves Glimmer and runs nothing heavy); it takes roughly 8 hours [hypothesis].

## Which set decides: the generated maps

**The primary gate set is the 40 generated maps.** Reasons: 40 maps against 13 gives a narrower across-maps interval; they were declared and hashed before any play; none went through navigation tuning. The 13 Freedoom maps get the same analysis, reported next to it, and never rescue or overturn the primary verdict. A Freedoom set that disagrees is reported as disagreement.

## Measures

- **First would-fire decision** (the primary's unit): in each game, the first decision whose observation reaches the cutoff. Up to it no arm has shown anything, so the prompts the arms saw were identical up to that point apart from the one-move card; the primary compares arms from this pre-treatment state, not over later decisions that earlier replies already shaped.
- **Mistakes at the first fire** (M1): the game's own tagged mistakes at that decision.
- **Progress after the first fire** (M2): route units covered from the start of that decision to the start of the decision 3 later (design setting: a lesson is shown for one decision, so its effect should appear within about a tenth of a 32-decision game). A window cut by the game's end (death or the last decision) runs to the last decision that began; a first fire at the last decision has no window. A fire with no window or no route reading has **no progress reading**: it is dropped from M2, never scored as 0, and counted per arm in the results file.
- **Secondary, descriptive**: the same two measures averaged over all of a game's would-fire decisions.
- **With-fire case**: a case in which both compared arms have a first would-fire decision. M1 and M2 are paired over with-fire cases (M2 further needs a progress reading in both arms; its case count is published).
- **Whole-game fitness**: 1.0 exit, plus 0.5 times furthest route share, minus 0.02 per tagged mistake, minus 0.5 for dying (weights are a judgment call [hypothesis]). Kills are reported, never scored.
- Intervals: two 95% percentile bootstraps, 10,000 draws, fixed seed 20261101: the **map interval** resamples maps (keeping each map's cases together, so a map counts in proportion to its number of cases; a map with no with-fire case contributes none to M1 and M2), the **case interval** resamples single cases. Both are published with the per-map differences. [established]
- Word per measure: `better` only if the low ends of BOTH intervals are above 0 (mistakes are negated so higher is better); `worse` only if both high ends are below 0; else `tie`.

## Decision rules

- **C1 (lessons minus none at the first fire, primary set)**: `underpowered` if fewer than 126 with-fire cases (the scorer applies this first, and the sentence says so, even if an interval clears 0). Else `worse` if M1 or M2 reads `worse`; else `supported` if M1 reads `better` (M2 not worse); else `tie`. A tie is reported as a tie.
- **C2 (one_move minus none, whole-game fitness, primary set)**: `supported` only if the word is `better` and the mean difference is at least 0.08 [hypothesis: a little under the map-level detectable effect with no between-map spread]. A `better` below 0.08 is reported with the word "better but small".
- Two claims, no correction; neither changes the other's verdict. No gate changes after results, no per-map or per-seed re-slicing, no extra seeds. If C1 reads tie, worse or underpowered, the pitch drops situational lessons and says why.

## Size (from the measured noise)

- First-fire basis (the primary), recomputed on the 9 fresh-validation with-fire cases [measured]: mistakes at the first fire 0.56 fewer with lessons (SE 0.18, paired SD 0.53); progress over the next 3 -267 route units (SE 273, paired SD 819). Same 9 of 18 cases have a first fire in both arms (a case has a first fire exactly when it has any fire). Fires without a progress reading: 2 (none) and 3 (lessons) of all fires.
- Needed with-fire cases: the 84 comes from the earlier check at the OLD cutoff 0.969 on all-fires means, not from this design; on the first-fire basis progress is noisier (SD 819, not 425). Planned: **at least 126 with-fire cases on the primary set** (the underpowered line), target 168 or more.
- Expected with-fire cases: 9 of 18 fresh-validation cases (50%) [measured], so the 360 generated cases are expected to give about 180 (the weak number: MAP10 never fired, 0 of 32 decisions, so fire rate varies strongly by map), and the 65 Freedoom cases about 33. At 180 cases the case-level detectable effect (80% power, 5%) is 2.8 times SD over the square root of n: mistakes about 0.11 per first-fire decision, progress about 171 route units [hypothesis, SDs from 9 cases]. The progress measure is therefore the weak one: a real progress loss smaller than about 170 units will read `tie`, not `worse`. The Freedoom set is underpowered for C1 by design and descriptive for it.
- Whole-game C2: the paired SD was 0.446 on 42 training cases [measured]; 360 cases give a case-level detectable effect of 0.065. At the map level, with a between-map spread of the effect like the 0.26 seen on 7 training maps [hypothesis], the standard error is about 0.048 and the detectable effect about 0.14, below the exploratory 0.17 and above the 0.08 bar. A `better` on both intervals therefore needs a steady effect across maps.

## Spend and stop rules

- Ledger cap $60 in all (~$12 used). This run's cap: **$10** (ledger name `heldout-onemove`). 1,275 games at about $0.0037 each is about $4.7, with replays under $6 [hypothesis]. Scoring replays use no model.
- [hypothesis] Ungraded games (design rule): an API or network error, or a reply the server returns empty or without usage, makes a game ungraded (replayed up to 3 times). A reply with content but no parseable move is not ungraded: it is played as a non-move and tagged. The results file publishes, per arm, the games started, the ungraded attempts (replays) and the cases dropped; the scorer refuses (raises) above 10% of the planned cases dropped, instead of reporting.
- Run mode: detached (`setsid nohup`, a log and a done-file), resuming from each arm's state file after any crash; on the 5080 with 6 game processes, spend cap 25 dollars on that machine's shared ledger.
- The runner stops, reports and does not continue if a hash, the code pin or a map file differs from what this file quotes.

## Disclosures

- The lessons are Spark's own, written from its paired training-map games; the one-move card is ours. The cutoff was set on validation maps whose seeds differ from the scored ones. The map set for the pitch is the generated set; Freedoom maps are the cross-check.
- ViZDoom version split: the exploration ran on ViZDoom 1.2.4 (Mac); the scored test runs on ViZDoom 1.3.2 (5080, Linux). Every arm of the test runs on the same version, on the same machine. Parity on one generated map with a fixed fake reply: route share 0.1308 and 3 mistakes on both versions [measured]. The results file records the version used.
- Fire counts depend on each arm's own trajectory; the none arm's would-fire decisions are decisions where a lesson would have appeared, not where one did.
- Both arms may die or stall; that is scored (death is in fitness; M1 and M2 are per-fired-decision means, so a game that ends early has few fired decisions).

## What the pitch may say

Only the sentence `held_out_score.py` builds from the numbers, with both intervals and the generated and Freedoom sets side by side. The words "evolved", "self-improving", "learned from its own mistakes" and "recursive" are never used.

## Results file

`results/evolve-onemove.json`: counts, ids, labels and intervals only (no card or lesson text): `code_commit`, `freeze_commit`, the pinned commit, this file's sha256, model id, dates, cases planned, scored and dropped, spend, both sets' claims with both intervals and per-map differences, fire counts per arm, and the sentence.

## Demo clips (named in advance)

OB0001 and MAP04 at seed 4001, no lesson against the winning arm, Muse Spark playing, shown whatever the games turn out to be. If a named game is ungraded after 3 replays, the clip is seed 4002 on the same map; no other substitution.

## Amendments

None.
