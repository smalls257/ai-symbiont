# Pre-registration DRAFT: Plug round 4, small trained judge + ranker agreement (NOT FROZEN)

Draft for the Sonnet re-check before the freeze. The freeze is its own commit, before any fresh-repo answer. Claim tags: [measured], [established], [hypothesis]. Round 3 stays reported as scored (judge pick 0.310 against thresholded ranker 0.166; H2 and H3 missed) [measured]. . Wording everywhere: "small trained judge + ranker agreement", never "retrieval".

## Question
On real later recurrences of a repository's own failures, does a small trained judge that must agree with the ranker cover more right lessons at no more than 5% wrong [established] than the round 3 judge alone?

## Primary (one)
Right-lesson coverage at wrong pick <= 0.05: the **agree rule** against **the round 3 judge alone as scored in round 3's design**. The agree rule = the round 3 judge (3-seed mean P(yes), as scored, no retraining) plus the ranker: the ranker's top lesson is answered only if the ranker's own score reaches a cut and the judge's P(yes) on it reaches a threshold. Both thresholds are fitted on validation only, with the nested repo-fold CV stricter target: the in-sample wrong target is the one whose nested-CV wrong pick is at most 0.05, and the coverage cost is printed (`scripts/routea/plug_r4_matched.py`). The judge-alone arm keeps round 3's frozen threshold. Habits (ranked-choice, 44 questions, >= 0.90) are a separate claim and never part of the primary.

"Right" for a merged twin lesson = the true fix is among the listed fixes (owner ruling). Twin lessons (same failed command and error) are merged in the store.

## Situations (primary set)
- **Positive items:** real later recurrences (the exact command and error in a later, different task of the same repository) in never-read plus meta2-only repositories. The pre-declared rule (2e244dc, d4aa9b4, be77a22) ended with this set because never-read repositories alone stayed under 150. **The run requires n = 251 recurrences in 89 repositories**; any other count is a refusal, not a smaller run [measured].
- **Negative items:** later failures in the same repositories with no matching lesson; the right answer is silence. They are counted from the committed rule before the freeze and listed by id.
- **Wrong-pick denominator:** all primary items (positives plus negatives); the claim sentence states it. Coverage is over positives.
- **Strict coverage row:** single-fix lessons only.
- **Secondaries, never deciding:** verified subset, loose key, Spark paraphrases (a separate prompt from training, disclosed; real and Spark reported apart), round-3-style situations labeled "string-match level".
- Note text is always verbatim from the stored lesson.

## Leakage statements
- `add_records` holds out the later tasks: no later task of a scored repository enters any store the scored arms read.
- Spark sees only stored lesson text (template-built), never AIDev comment or patch text and never a private session.
- The base judge's training repositories are disjoint from the scored repositories (`plug_r3.check_splits`).
- Round 3's 40 repositories are validation here and are used for every choice below; this is disclosed, not hidden.

## Silent Fallbacks refused
A failed nightly training run, unparsable model output, an invalid lesson id, or a missing repository stops the run or counts as a failure; none is ever read as silence. The scored runner refuses to start unless n = 251 / 89 repositories.

## Arms
- **Primary arms:** agree rule against the round 3 judge alone (above).
- **Fair reference for training:** the round 3 judge (3-seed mean) with the same agree rule, fitted the same way.
- **Nightly training (arm A): tested and rejected, descriptive only (owner closed it).** Per-repo nightly adapter from the fixed merged judge (rich input, 10% habit replay, Spark-invented situations, near-misses from round-3 validation only), read at strength 1.0, with the same agree rule and nested-CV target, against the fair reference. As built it is more cautious, not more accurate: on validation it covers less at a matched wrong rate (below) [measured]. It is not scored on fresh repositories and no claim rests on it.
- **Separate pre-registered row:** the rule's own gain, fair reference with the rule against the round 3 judge alone.
- **Descriptive:** learned-lesson slice check (below); floor rows (basic RAG, nothing).
- Arm B (weights name the lesson id) is not run in this round (owner ruling).

## Validation numbers (round 3's 40 repos, 330 items)
Files: `results/plug-r4-explore.json`, `plug-r4-combine.json`, `plug-r4-combo.json`, `plug-r4-slice.json`, `plug-r4-matched.json`, `plug-r4-power.json`.

Coverage at CV wrong pick <= 0.05, nested CV, twins merged [measured]:

| Scorer | Pick | Wrong | At fixed 0.05 target: pick / wrong | Coverage cost of the stricter target |
|---|---|---|---|---|
| Reference + agree rule | 0.527 | 0.039 | 0.655 / 0.097 | 0.128 |
| Arm A, strength 1.0 | 0.394 | 0.049 | 0.473 / 0.058 | 0.079 |
| Arm A, strength 0.5 | 0.273 | 0.039 | 0.449 / 0.064 | 0.176 |

Habits are the mean over the per-repo nightly adapters (40 adapters for arm A), and over the three seeds for the reference [measured]: round 3 judge 0.795; arm A at strength 1.0, 0.752; at 0.5, 0.891. Lowering the strength buys habits at a cost in matched coverage.

Single changes against the round 3 judge (pick / wrong, in-sample fit) [measured]: rewritten lessons 0.127 / 0.046; five seeds 0.261 / 0.049; 3B 0.230 / 0.030; rich input 0.261 / 0.027 (habits 0.909); nightly 10% replay 0.345 / 0.042 (habits 0.612); nightly 25% replay 0.321 / 0.049 (habits 0.688); round 3 judge 0.230 / 0.036.

**Learned-lesson slice (descriptive secondary)** [measured], cross-validated, rates over all items, wrong picks by who learned the chosen lesson: reference right 0.327, wrong 0.097; arm A at 0.5, right 0.224, wrong 0.064; at 1.0, right 0.236, wrong 0.058. Every wrong pick in all three is a sibling lesson of the same repository; none is a base-trained or another repository's lesson.

## Decision rule
1. Primary reads **better** if the repo-clustered bootstrap 95% interval (10,000 resamples, seed 0) of the coverage gain has its lower bound above 0 and the mean gain is at least 0.05; **worse** if the upper bound is below 0; **tie** otherwise [established].
2. Safety limit on the primary arm: wrong pick (all primary items) at most 0.05, with the **repo-clustered bootstrap upper bound** at most 0.10. The Wilson bound and an assumed design effect are not used; the measured ICC is reported [established]. Otherwise the sentence reads "coverage gain, safety not shown".
3. The rule's own gain row (fair reference with the rule against the judge alone): same intervals, reported as is.
4. Habits: seed-mean ranked-choice >= 0.90, the untrained 1B beside it; separate, never folded into the primary.
5. No per-seed re-slicing, no threshold or gate change after results, amendments only as new dated files.
6. Multiplicity: one primary; the rule-gain row is a pre-registered secondary, reported without correction, none changes the primary's reading.

## Power (measured on validation, `results/plug-r4-power.json`)
- Mean per-repo gain of the agree rule over the judge alone (nested CV, twins merged): 0.0785; paired SD per repo 0.418, scaled to the scored set's pick items per repo (251 / 89 against 4.1 on validation): 0.506 [measured].
- MDE at 80% power, 5% two-sided, 89 repos: (1.96 + 0.84) x 0.506 / sqrt(89) = 0.150 [established]. **The expected gain (0.08) is below the MDE: the primary is underpowered and may read "tie" even if the effect is real.** This is stated before the run.
- Wrong-pick ICC across repositories: 0.093 [measured]; the clustered bootstrap bound carries it.
- Validation is itself the fit set, so these are optimistic; the repo-fold CV removes that for the rates but not for the SD.

## Known limits
Twins are merged by the owner's ruling and change what "right" means; the fair reference picks more than nightly training at a matched wrong rate on validation; the nightly adapters lose habits unless the strength is lowered; Spark-invented situations are a learned style; the validation repositories were used for every choice; thresholds must transfer to fresh repositories.

## Spend
Spark: 557 rewrites and 4,764 invented situations already made, $0.18 [measured]; any new laptop Spark job exports the ledger cap, 35 dollars now [established]. Training and scoring on the 5080 when a window opens.
