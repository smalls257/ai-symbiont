# Code-fix lessons study on SWE-smith: result (scored once, 2026-10-31)

Claim tags: [measured], [established], [hypothesis]. Frozen prereg: `prereg/2026-10-31-code-fix-lessons.md` (freeze 1aed1c4); numbers in `results/plug-r4-smith-decision.json`. Data: public SWE-smith trajectories, pydantic/pydantic and getmoto/moto, 924 items (462 recurrences, 462 negatives). Disclosed: synthetic injected bugs, inferred failures (no exit codes), a new lesson definition, a stand-in task order from a seeded hash.

## Result
- **Nightly arm against the agree rule (primary):** per-task mean coverage 0.611 against 0.000, gain 0.611, task-clustered interval [0.556, 0.666] [measured].
- **Wrong picks:** 5 of 924 items wrong (0.54%), precision 97.8%, 227 answered; exact Clopper-Pearson 95% upper bound 1.26%, below the pre-set 5% bar [measured].
- **Claim reading:** better, by the pre-registered rule (interval above zero, gain at least 0.05, exact bound below 0.05) [measured].
- **Agree rule against judge alone:** both answered nothing on these items (coverage 0.000 each), a tie [measured].

## What the comparator means
The round 3 judge, at its frozen thresholds, never said yes on SWE-smith items, so the agree rule and the judge alone have zero coverage. The comparison therefore shows that nightly training recovers coverage where the off-the-shelf judge does not transfer (a domain gap), not that training beats a working baseline [established]. Two repositories, synthetic bugs and a new lesson definition limit the claim to this kind of data; round 4's own nightly result stays no claim.

## Operational notes
The 5080 GPU was held by Glimmer, so training and scoring ran on the laptop (MPS, judge venv); `base-judge-s0` and `base-general` were rebuilt locally by merging the pinned adapters (numerics may differ from the desktop copies in the last bits). Launcher fixes after the freeze (e22a182 and later) changed no design, rule, data or threshold.
