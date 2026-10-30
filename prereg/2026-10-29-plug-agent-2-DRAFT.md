# Pre-registration: Plug agent outcome, phase 2 (PLUG-AGENT-2)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any scored branch runs. After the freeze only a dated amendment may change anything, and an amendment cannot change the pool, labels, arms, measures, the primary contrast, the stop rule or the claim templates. Only the number of branch points N may change after the smoke test.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Supersession

PLUG-AGENT-1 (`prereg/2026-10-29-plug-agent-outcome.md`, frozen at 52e6154, 29 tasks, one Glimmer run per arm) was **superseded by the owner on 2026-10-29 before any run**. No PLUG-AGENT-1 arm ran a task [established]. Its code (`scripts/routea/plug_agent_*.py`) and its Opus-fixed rules carry over unless a section below says otherwise. Neither prereg decides anything about round 3.

## Question and the claims it supports

1. **Forced delivery (primary, scored).** At the moment a coding agent makes a mistake that a stored, applicable lesson describes, does showing that lesson's note, verbatim, make it less likely to make the same mistake again than showing nothing? The note is always the correct, pre-labeled lesson; the judge is not involved.
2. **Derived end-to-end claim (a claim, labeled "derived", not a pilot).** Forced-delivery prevention times Plug's scored coverage, from round 3 (a8bf9ec) or round 4 if scored first. Its interval resamples **both** parts: branch points for the prevention, repositories for the coverage (the scored round's per-repository data). **Independence assumption** [hypothesis]: a note's efficacy at the points where the judge speaks equals its efficacy at all points. The judge-gated direct arm checks it.
3. **Judge-gated direct arm.** The judge's own pick at its frozen thresholds against no note; its status is decided by the pre-registered threshold below.

## Design: branch points

- **Branch point.** The first moment in a run at which the agent executes a command that fails with a known key (key rule below). All arms continue from the same state: the same container filesystem (committed with `docker commit`, or rebuilt by replaying the prefix's commands in a scrubbed container) and the same message history.
- **Sources of branch points.** (a) Own `none` prefix runs on the pool's labeled tasks, run on the laptop Glimmer. (b) *Sources only*: plain-Glimmer screening runs of Core's, whose prefixes came from the Strix Glimmer (same GGUF sha256), if the Core agent supplies their paths and their tasks are labeled with the same frozen prompt. Their outcomes (solved or not) are never used and never scored for Core; only their state up to the first known mistake is reused, and the branches run on the laptop. The report states the split between sources and shows the primary for each source apart.
- **Arms at each branch point** [established]. `none` (the note is absent), `forced` (the correct lesson's note appended verbatim under the failing observation). The correct lesson is the `applies`-labeled lesson whose key equals the failure's key (the lowest lesson id if several). Judge-gated and exploratory arms: `judge` (the round-3 3-seed judge at its frozen thresholds from `selection.json`), `rag` (top 3 by the lexical ranker) and `ranker` (round-3 thresholded ranker). **Arms with identical input at a point share branches**: where the judge stays silent its input equals `none`'s, and where it picks the forced lesson its input equals `forced`'s; only a different note adds branches. The report counts how many branches each secondary arm actually needed.
- **Branches per arm per point: B = 6** (justification in Sizing), at the sampling temperature below, each a continuation of **W = 15 model calls** after the branch point. A branch ends at W calls, at a submit, or at a wall cap, whichever comes first.
- **No `none2` arm.** The within-arm spread of the B branches at each point is the noise floor; `none2` is dropped because this design replaces it [established, by construction].
- **Sampling.** Temperature 0.6, no seed, so the B branches of an arm are independent samples [hypothesis]. (PLUG-AGENT-1's temperature 0 would make every branch of an arm identical.)

## Frozen rules carried over from PLUG-AGENT-1 [established]

- The judge being down stops the run with an error, recorded as `judge_down`, never as "no note" (Silent Fallback).
- A void branch (infra or model_api error) is requeued once; if still void it is dropped and listed with its reason. A branch that reaches the wall cap counts its repeats up to the cutoff; it is not void.
- Full config pinning: one config file (`results/plug-agent-2-config.json`), sha256-checked by the runner. It holds the GGUF sha256 and the llama-server version, temperature, W, B, step limit, token cap, wall cap, thresholds, `selection.json` and adapter hashes, the pool, label, label-prompt and key-rule file hashes, the requeue cap and the dollar cap on Spark labeling.
- Scrubbed containers (base-commit history only); a failed scrub voids the point.
- Fixed point order: sha256 of `plug-agent-2:<instance_id>`; all arms of a point finish before the next point starts.
- Hold-out: round 3's 40 scored repositories do not occur in the pool.

## Pool (defined by a rule, independent of round 4's scored set)

- **Repositories.** Repositories in the nebius OpenHands exports on disk (CC-BY-4.0, `spark_safe`) that (1) are **not** among the 125 repositories of round 3's pool, (2) are not one of Core's six repositories, (3) have at least two dated tasks, and (4) have at least one **loose** real recurrence by the counter at d4aa9b4. The rule counts recurrences per repository only; it does not use round 4's primary set or scored selection. Result: 118 repositories [measured].
- **Round-3 judge training.** Round 3 trained the judge on the lessons of its 60 meta-train repositories and fitted thresholds on its 10 validation repositories, all inside its 125-repository pool. Rule (1) removes every one of those, so **no test instance's own session was in the judge's training or threshold fit** [established, by construction].
- **Later tasks** (every dated task except the repository's earliest): 946 [measured]. **Candidates**: a docker image and at least one earlier same-repository lesson: 667 [measured] (73 without an image, 206 without an earlier lesson).
- **Store per task.** Same-repository lessons mined from instances created strictly before the task (distinct failures, the 40 most recent), in template prose; for the pilot secondary arms, distractors from other repositories up to 60 as in PLUG-AGENT-1. Never the task's own instance or a later one.
- **Privacy.** Only public SWE-rebench task text and template-built lessons reach Spark. No AIDev text and no private session is read [established].
- **Coordination with Plug round 4.** Round 4 scores the judge on situations from the same sessions; this test runs agents on the tasks. Neither writes the other's outputs. The controller receives this test's repository list to compare with round 4's scored repositories; overlap is reported, not removed.

## "A lesson applies" (frozen, done)

- Spark (`muse-spark-1.3-contributor`, temperature 0, through `symbiont.egress`) labeled each (task, lesson) pair from the public issue text (cut at 6,000 characters) and the lesson's template prose with the frozen prompt `scripts/routea/plug_agent2_label_prompt.md` (sha256 `dad7b47d...`, committed in 4d73f9a before the first call). **667 tasks, 0 excluded, 360 applies tasks, 857 of 2,823 pairs labeled `applies`; cost $0.12** [measured]. Labels: `results/plug-agent-2-labels.json` (commit 3814118, before the smoke test and before any scored run); the runner checks the file hash.
- Unusable replies are retried once, then the task is excluded and listed; a failed label is never read as `does_not_apply`. None occurred.
- Hand check of 30 pairs by sha256 order: 24 agreed, 6 questionable (generic `ModuleNotFoundError` lessons labeled inconsistently) [measured]; no label was changed.

## Known mistake and repeat (frozen)

- A failed command's **key** is `(error class, program, target file)` (`scripts/routea/plug_agent2_keys.py`, tested, pinned by hash). A key with an empty error class, an empty or "-" program, or an empty or "-" target file does not exist and never counts as known; this excludes generic keys such as `(ModuleNotFoundError, python)` [established, by construction].
- A **known mistake** is a failed command whose key equals the key of a lesson labeled `applies` for this task.
- **Repeat.** The branch point's key fails again within the branch's W calls.

## Primary outcome and the derived claim

**Primary (forced delivery).** Per point, the repeat share of the `forced` branches minus that of the `none` branches (B branches each); the unit is the point, never the branch. The statistic is the mean over points of that difference d, with a paired sign-flip permutation test over points (100,000 flips, seed 0) and a BCa interval (10,000 resamples, seed 0) [established, declared now]. Also reported: the two shares ("from X% to Y%"), each source apart.

**Derived end-to-end claim.** E = c x d, where c is Plug's scored coverage (the share of applicable situations in which the judge shows the correct lesson at the frozen threshold, round 3: 0.310 at 3 seeds and 5.3% wrong picks, a8bf9ec [measured, round 3]) and d is the forced-delivery prevention in points. The interval resamples points for d (10,000 resamples, seed 0) and repositories for c from the scored round's per-repository results (10,000 resamples, seed 0) jointly, so both uncertainties enter. The claim is labeled "derived", states the independence assumption, and does not include the cost of a wrong note (that is not measured by forced delivery) [established].

**Judge-gated direct arm: pre-registered threshold.** By the fixed cutoff time (set by the coordinator before the scored run), if the test has **at least 150 branch points and at least 50 points at which the judge speaks**, the judge-gated arm is a **scored test** with its own rule: the mean per-point difference (judge-gated minus none), same inference as the primary, claim only if the BCa interval excludes zero and its sign-flip p is below 0.05. If not met, it is reported as a **consistency check** of the derived estimate (its estimate beside E, no claim). At the measured capacity this threshold is **not expected to be met** [hypothesis]. Where the judge is silent its continuation equals `none`; where it picks the forced lesson it equals `forced`; branches are run only where its note differs, in the fixed point order.

## Smoke test and the one stop rule (frozen before the smoke test)

- 25 applies tasks chosen by sha256 order of `plug-agent-2-smoke:<instance_id>` from the 360, `none` arm, whole runs on the laptop Glimmer, 1 run each (2 each only if fewer than 10 runs hit a first known mistake). **These 25 tasks are excluded from scoring.** [hypothesis]
- It reports: runs with a first known mistake, the repeat share within 15 calls of it, the share of failures with no key, the top keys, steps and wall time per run.
- **Stop rule.** Go to the scored phase only if at least **10 smoke runs** hit a first known mistake, **and** the repeat share (within W = 15 calls, whole-run repeat counted as in the measure script) is at least **30 percent**, **and** the recomputed minimum detectable difference below is at most 20 points at the points the pool can supply. Otherwise stop and the owner decides. More tasks are not the fallback. Only N may change after this rule is read out.
- **Early reading** (two finished runs so far): 4 failed commands, none with a key; the agent's mistakes are generic interpreter failures [measured]. If the smoke confirms that the rate of keyed known mistakes is very low, the pool supplies too few branch points and the stop rule fires.

## Agent and infrastructure

- Plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M` (GGUF sha256 `4cc57c0f...f60e`, same as the Strix), llama.cpp 0.8.0 build 11960 (commit 8642541b2) on the owner's laptop, 2 slots of 32k, flash attention, `--jinja`; reasoning low, 4,096 tokens per reply. Containers (mini-SWE-agent, scrubbed, no network) on the 5080 CPU. The bearer key comes from the environment and is never logged or written to a trajectory. The judge, if used, runs on the laptop CPU or Metal; the 5080 GPU stays with Core. [measured]
- **Speed** [measured, one task]: about 14 tok/s generation and about 115 tok/s uncached prompt with one stream; two streams run at 8 to 9 tok/s each (about 1.25 times one slot in total); about 21 s per model call; a 53-step run took 18 min. [established]
- Images are pulled just in time with their registry size checked first (limit 8 GB, disk floor 60 GB) and removed after the point's last branch. Long drivers run detached on the 5080 with a log, a done-file and resume.

## Sizing (stated before any scored run)

- **Capacity** [hypothesis, from the measured speed]: two slots give about 214 model calls per hour, so about 14 fifteen-call branches per hour. One point with `none` and `forced` at B = 6 is 12 branches, or about 0.85 laptop hours; the pilot arms add branches only where their note differs. A prefix costs about 0.1 to 0.3 hours when it reaches a known mistake, more when it does not; Core's screening sources need only a replay [hypothesis].
- **Points:** with about 30 laptop hours for the scored phase, **about 30 branch points** (36 with free sources) [hypothesis]. The 150-point threshold of the judge-gated arm needs a prefix source far larger than the laptop can branch; it is met only if Core's plain-Glimmer screening runs supply many sources and the judge's branches stay few [hypothesis].
- **Variance.** Binomial within a point at repeat shares 0.4 and 0.2 and B = 6 gives a variance of the paired difference of about 0.08; between-point variation of the effect adds about 0.02 to 0.05 [hypothesis]. SD about 0.32 to 0.36.
- **Smallest detectable difference** (80% power, two-sided 5%, N = 30 points): 2.8 × SD / sqrt(30) = **about 16 to 18 points** (about 15 at N = 36) [hypothesis]. B = 6 against B = 4 moves it by about 1 point; the between-point variation, not B, is the floor. "Pilot" stays unless the smoke's measured numbers bring it to 15 points or less.
- The hit rate of keyed known mistakes is the unknown that matters most: it decides how many points exist. The smoke measures it.

## Claim templates (fixed now)

1. **Forced delivery.** "In N branch points where Glimmer had just made a mistake that a stored lesson describes, showing that lesson's note verbatim cut repeats within 15 steps from X% to Y% (difference [estimate, BCa interval, sign-flip p]); the test detects differences of at least [MDE]." Labeled **forced delivery**.
2. **Derived end-to-end.** "Plug shows the correct lesson in a fraction c of applicable situations [interval over repositories, round 3]; showing it cuts repeats by d points [interval over branch points]; so Plug would cut repeats by about c x d points [joint interval]." Labeled **derived**, with the independence assumption stated.
3. **Judge-gated.** Scored test if the threshold is met; otherwise "consistency check: the judge-gated difference [estimate] beside the derived [estimate]; no claim".

The report never says "the judge helps agents" and never uses speed-of-learning words.

## Not in this prereg

Any change to the judge, its thresholds or training; round 3's 40 scored repositories; Core's D2 scoring (Core's runs are sources of state only); solve rate.
