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

## Exploration so far (validation = round 3's 40 repos, 330 items; see results/plug-r4-explore.json, plug-r4-combine.json)
[measured]; thresholds fitted in-sample on the same items except where marked CV. Numbers in the report table of the session; to be pasted here before freeze.

## Decision procedure (to be fixed before freeze)
Threshold fitted on validation only; scored once on fresh repos; per-repo paired bootstrap, 10,000 resamples, seed 0; wrong pick over all items; decision rule per round 3 (better/tie/worse); no per-seed re-slicing; no gate change after results.

## Power
Situations: 251 in 89 repos [measured]; with a true 5% wrong rate the upper bound clears 10% only with enough pick items; MDE and upper-bound rule computed from validation per-repo SD before freeze [hypothesis: ~53 repos per 4 wordings, from the 13:36 ruling].

## Known limits
Twins (all CV wrong picks share command and error with the right lesson) now merged; per-repo nightly threshold is fitted in-sample on validation and must transfer; nightly adapters lose habits unless replay is larger (see exploration); GPU/seed noise; Spark invented situations are a learned style.

## Spend
Spark: 557 rewrites and 4,764 invented situations already made, $0.18 [measured]; new laptop Spark jobs export the ledger cap, now 35 dollars [established]. Training on the 5080.
