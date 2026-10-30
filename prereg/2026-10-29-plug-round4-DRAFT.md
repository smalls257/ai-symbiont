# Pre-registration DRAFT: Plug round 4, small trained judge + ranker agreement (NOT FROZEN)

Draft for the Sonnet re-check before the freeze. The freeze is its own commit, before any fresh-repo answer. Claim tags: [measured], [established], [hypothesis]. Round 3 stays reported as scored (judge pick 0.310 against thresholded ranker 0.166; H2 and H3 missed) [measured]. Wording everywhere: "small trained judge + ranker agreement", never "retrieval".

## Question
On real later recurrences of a repository's own failures, does a small trained judge that must agree with the ranker cover more right lessons at no more than 5% wrong [established] than the round 3 judge alone?

## Primary (one)
Right-lesson coverage at wrong pick <= 0.05: the **agree rule** against **the round 3 judge alone as scored in round 3's design**. The agree rule = the round 3 judge (3-seed mean P(yes), as scored, no retraining) plus the ranker: the ranker's top lesson is answered only if the ranker's own score reaches a cut and the judge's P(yes) on it reaches a threshold. Both thresholds are fitted on validation only, with the nested repo-fold CV stricter target: the in-sample wrong target is the one whose nested-CV wrong pick is at most 0.05, and the coverage cost is printed (`scripts/routea/plug_r4_matched.py`). **The judge-alone comparator is defined once, as deployed:** the round 3 judge, 3-seed mean P(yes), over the ranker's top-10 shortlist, at its frozen round 3 threshold 0.99 (amendment 1), applied to its own scores and never refit; twins merged in the store for both arms. **Metric:** coverage = the per-repository mean of right answers over that repository's positive items (each repository weighs the same; repositories with no positive item are excluded and counted), and the bootstrap resamples repositories. Wrong pick = answered-but-not-right over all primary items, negatives included (negatives count in the wrong-pick denominator and in silence). Habits (ranked-choice, 44 questions, >= 0.90) are a separate claim and never part of the primary.

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

## Pre-declared fallback primary
If continuous training (the owner's recipe: learn from misses, Spark labels, retrain each night from the round 3 judge on all data, 25% general replay; and the alternate arm with a retrained ranker) does not beat the fair reference (round 3 judge with the agree rule) at the same wrong-pick cap in nested repo-fold CV on validation, the round 4 primary is **"trained judge vs RAG floor + untrained 1B"**: the round 3 judge (with the agree rule) against basic RAG and against the untrained 1B on the same primary items. The exploratory result decides which primary is frozen; the other is then not run as a claim. [established]

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

## Power (measured on validation on exactly the primary metric, `results/plug-r4-power.json`)
- Per-repo mean coverage over the 40 validation repos, twins merged [measured]: agree rule (nested CV) 0.519, round 3 judge alone at the frozen 0.99 threshold 0.348; mean paired gain 0.171. Pooled over items: 0.527 against 0.358, so per-repo and pooled agree. Wrong pick is 0.039 for both (pooled, validation items including silence items as negatives).
- Paired SD per repo 0.377, scaled to the scored set's pick items per repo (251 / 89 against 4.1) 0.456. MDE at 80% power, 5% two-sided, 89 repos: (1.96 + 0.84) x 0.456 / sqrt(89) = 0.135 [established]. The validation gain is above the MDE, but validation is also the fit set, so the gain is optimistic and no expected gain is claimed for the scored set [hypothesis].
- A first power draft (0.0785 gain, MDE 0.150) used a judge-alone comparator refit in cross-validation, not the frozen threshold; it is withdrawn. The code is `plug_r4_power.py`; `nested_choices` and `per_repo_pick` were checked (all 40 repositories have 3 to 7 positive items; pooled and per-repo means differ by under 0.01).
- Wrong-pick ICC across repositories: 0.093 on validation items [measured]; it is recomputed on the primary's own items once the negatives are counted.

## Built for the freeze (all [measured] counts from the build)
- **Primary item builder** `scripts/routea/plug_r4_primary.py`: each recurrence is a later failure whose exact key an earlier task's lesson has, with the store as it stood before that task (tasks ordered by SWE-rebench creation date, ties by id; identical lessons merged, different-fix twins kept and scored as one). It reproduces the pre-declared **251 recurrences in 89 repositories** and refuses any other count (`PrimaryCountError`). Prompts hold 60 lessons: the store plus seeded distractors from other primary repositories that never share the failure key.
- **Negative items:** later failures with no exact or loose match in the store; per repository as many as it has positives, chosen by a seeded hash; one repository had fewer available, so the total is **250 negatives** (a count, not a fallback). Listed by id in `results/plug-r4-primary-negatives.json`. Single-fix positives (strict coverage row): 175 of 251.
- **Ranker reach:** the applicable lesson is in the ranker's top 10 for 99.6% of positives (top 1: 68.9%, top 3: 95.2%, top 5: 99.2%). [measured]
- **Agree-rule thresholds, fitted on validation only** (`plug_r4_scored.py fit`, `results/plug-r4-selection.json`): the nested-CV stricter target is 0.03 in-sample wrong pick; the rule is ranker score >= 10.0 and judge P(yes) >= 0.96. The judge-alone comparator uses the frozen 0.99.
- **Scored runner** `plug_r4_scored.py` (pins, fit, check, decide) with `plug_r4_primary_stats.py` and `plug_r4_scored.sh` (three round 3 adapters, no training), tests in `tests/scripts/test_plug_r4_primary.py`. Refusals: n other than 251 / 89; any changed primary item, query or negative-list file; any changed adapter weight hash; a changed selection file; a missing seed file; scores that do not cover exactly the primary queries; a score outside 0 to 1. Pins are in `results/plug-r4-pins.json`; the desktop adapters have the same hashes as the laptop's.
- **Secondary row in the decision output:** the ranker at the same cut with no judge (judge threshold 0), so the judge's own contribution to the agree rule is visible.
- **ICC on the primary's own items** depends on which answers are wrong, so it is computed by `decide` after the scored run (`wrong_pick_icc`) and reported then; the validation ICC (0.093) stands until then.
- **GPU estimate for the scored run:** 5,010 queries per seed; round 3 scored 3,300 queries in about 35 s per seed, so about 55 s per seed plus about 20 s model load: **about 4 to 5 minutes for all three seeds**, 10 minutes with margin [hypothesis].

## Known limits
Twins are merged by the owner's ruling and change what "right" means; the fair reference picks more than nightly training at a matched wrong rate on validation; the nightly adapters lose habits unless the strength is lowered; Spark-invented situations are a learned style; the validation repositories were used for every choice; thresholds must transfer to fresh repositories.

## Spend
Spark: 557 rewrites and 4,764 invented situations already made, $0.18 [measured]; any new laptop Spark job exports the ledger cap, 35 dollars now [established]. Training and scoring on the 5080 when a window opens.
