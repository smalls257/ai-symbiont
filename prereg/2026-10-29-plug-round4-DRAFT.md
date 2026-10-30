# Pre-registration DRAFT: Plug round 4, nightly training on later recurrences (NOT FROZEN)

Draft for Opus review. Nothing here is frozen; the freeze is its own commit, before any fresh-repo answer. Claim tags: [measured], [established], [hypothesis]. Round 3 stays reported as scored (judge pick 0.310 vs thresholded ranker 0.166; H2 and H3 missed).

## Question
Does a per-repo nightly judge (or weights that name the lesson) cover more of the right lessons at no more than 5% wrong (limit set by the owner) [established] than the once-trained judge, on real later recurrences in repos it has not read?

## One primary
Right-lesson coverage at wrong pick <= 0.05 (upper-bound rule sized by power, to be fixed from the MDE below before freeze). Habits (>= 0.90) is a separate claim, never folded into the primary. "Right" for a merged twin lesson = the true fix is among the listed fixes; the 2+ fix rate is reported.

## Arms (owner-defined)
- Reference: ranker + once-trained judge (round 3 merged seed-0 base or 3-seed ensemble) + lesson list.
- A: Reference + nightly per-repo judge, retrained from the fixed base each night on all lessons so far (Spark-invented situations, near-misses from round-3 validation mistakes only, habit replay 10-25%). [established]
- B: weights only, names the lesson ID from memory (constrained decoding + "none").
- Floor: basic RAG, and nothing.
Options carried only if they held on validation: seed ensemble, "applies when" triggers, rich input, the two-threshold rule (change 6).

## Situations
PRIMARY: real later recurrences (exact command + error in a later, different task of the same repo) in never-read + meta2-only repos (251 in 89 repos; rule 2e244dc, d4aa9b4, be77a22). Secondaries: verified subset, loose key, Spark paraphrases (separate prompt from training, disclosed, reported apart from real), round-3 style labeled "string-match level". Note text verbatim from the stored lesson.

## Exploration so far (validation = round 3's 40 scored repos, 330 items; thresholds fitted in-sample on them unless marked CV)
Files: `results/plug-r4-explore.json`, `results/plug-r4-combine.json`, `results/plug-r4-combo.json`.

| Row (single changes) | Pick | Precision | Wrong | Silence | Habits |
|---|---|---|---|---|---|
| Round 3 judge, 3 seeds | 0.230 | 0.760 | 0.036 | 0.958 | 0.795 |
| Rewritten "applies when" | 0.127 | 0.583 | 0.046 | 0.952 | not run |
| Five seeds | 0.261 | 0.729 | 0.049 | 0.933 | 0.864 / 0.614 (s3 / s4) |
| 3B, half learning rate | 0.230 | 0.792 | 0.030 | 0.970 | 0.795 |
| Rich input | 0.261 | 0.827 | 0.027 | 0.958 | 0.909 |
| Nightly, 10% replay [measured] | 0.345 | 0.803 | 0.042 | 0.946 | 0.612 |
| Nightly, 25% replay [measured] | 0.321 | 0.768 | 0.049 | 0.927 | 0.688 |
| Two-threshold rule, CV (round 3 judge) | 0.497 | n/a | 0.061 | n/a | n/a |

[measured] Combo (nightly 10% replay + rich input + merged twins; twin pick counts right), 40 repos, by adapter scale at read time (no retraining); CV = repo-fold cross-validated:

| Scale | Habits | Judge alone, in-sample pick / wrong | Two-threshold, in-sample pick / wrong | Two-threshold CV pick / wrong / silence |
|---|---|---|---|---|
| 0.5 | 0.891 | 0.212 / 0.030 | 0.479 / 0.049 | 0.449 / 0.064 / 0.879 |
| 0.6 | 0.863 | 0.285 / 0.049 | 0.467 / 0.049 | 0.449 / 0.067 / 0.873 |
| 0.7 | 0.830 | no safe point | 0.479 / 0.049 | 0.455 / 0.058 / 0.885 |
| 0.8 | 0.802 | no safe point | 0.491 / 0.049 | 0.467 / 0.058 / 0.885 |
| 0.9 | 0.772 | no safe point | 0.509 / 0.049 | 0.473 / 0.058 / 0.885 |
| 1.0 | 0.752 | no safe point | 0.515 / 0.049 | 0.473 / 0.058 / 0.885 |

40% replay on 5 repos only (too few to read; habits 0.886 to 0.896, no gain over 10% at the same scale) [measured]. All rows [measured]; "no safe point" means judge alone cannot meet wrong <= 0.05 with silence >= 0.80 there.

Reading: the ranker-plus-judge two-threshold rule carries the coverage gain (about 0.45 CV against the round 3 judge's 0.25) but its CV wrong pick is 0.058 to 0.067, above 0.05, at every scale [measured]. Lower scale buys habits (0.891 at 0.5, still under 0.90) at about 0.02 of pick [measured]. Nothing explored meets both bars.

## Arm A setting to pre-register
Nightly adapter from the fixed merged rich judge, 10% habit replay, rich input, twins merged, read at adapter scale 0.5, decided by the two-threshold rule with both thresholds fitted on validation only. Scale is chosen for habits, the rule for coverage; the 0.5 choice is made now, before any fresh-repo answer, and no scale is re-picked after scoring [established]. Expected: habits just under 0.90, so the habits claim is stated as separate and may fail; the primary has a CV wrong pick above 0.05 on validation, so the upper-bound rule below may refuse the claim [hypothesis]. The Opus review should decide whether a safer margin (a threshold fitted at wrong <= 0.03) is pre-registered instead.

## Decision procedure
1. Fit on validation (round 3's 40 repos, disclosed as used for every exploratory choice above): one threshold pair, the lowest-wrong point with silence >= 0.80 and wrong <= 0.05, grid as `plug_judge_cli.GRID` and ranker score 0 to 30 step 0.5.
2. Score once on the primary situations (real later recurrences, 251 in 89 repos), twins merged, per-repo clustered bootstrap, 10,000 resamples, seed 0.
3. Primary: right-lesson coverage of arm A minus Reference, paired by repo. Reads better if the lower bound is above 0 and the gain is at least 0.05; worse if the upper bound is below 0; tie otherwise [established].
4. Safety limit on the primary: wrong pick of arm A at most 0.05 with the 95% Wilson upper bound at most 0.10 (cluster-inflated by a design effect of 1.5); if the bound is above 0.10, the claim sentence says "coverage gain, safety not shown" [established].
5. Habits are a separate claim: seed-mean ranked-choice habits >= 0.90 on the 44 questions, the untrained 1B printed beside it.
6. Arm B and the floor rows are descriptive; the counters/RAG row prints beside every learned row.

## Power (from the real-recurrence counts)
251 recurrences in 89 repos [measured]. At a true wrong rate of 5%, the Wilson upper bound over 251 items is 0.087 unclustered, and the smallest n with upper <= 0.10 is 130 [established]; with a design effect of 1.5 the effective n is about 167, so the bound lands near 0.10: borderline [established]. At a true 3% the upper bound is 0.062 [established]. Coverage MDE for A against Reference at 80% power: with coverages 0.45 and 0.25 and item-level correlation 0.3 to 0.5, 0.083 to 0.098 unclustered, so the expected gain (about 0.2 on validation CV) is detectable [established; the correlation is assumed, to be replaced by the measured paired SD from validation before freeze]. The verified subset and Spark paraphrases are secondaries and are not powered for any claim.

## Known limits
Twins (all CV wrong picks share command and error with the right lesson) now merged; per-repo nightly threshold is fitted in-sample on validation and must transfer; nightly adapters lose habits unless replay is larger (see exploration); GPU/seed noise; Spark invented situations are a learned style.

## Spend
Spark: 557 rewrites and 4,764 invented situations already made, $0.18 [measured]; new laptop Spark jobs export the ledger cap, now 35 dollars [established]. Training on the 5080.
