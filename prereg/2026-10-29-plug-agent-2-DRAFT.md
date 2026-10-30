# Pre-registration: Plug agent outcome, phase 2 (PLUG-AGENT-2)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any scored branch runs. After the freeze only a dated amendment may change anything, and an amendment cannot change the pool, labels, arms, measures, the primary contrast, the stop rule or the claim templates. Only the number of branch points N may change after the smoke test.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Supersession

PLUG-AGENT-1 (`prereg/2026-10-29-plug-agent-outcome.md`, frozen at 52e6154, 29 tasks, one Glimmer run per arm) was **superseded by the owner on 2026-10-29 before any run**. No PLUG-AGENT-1 arm ran a task [established]. Its code (`scripts/routea/plug_agent_*.py`) and its Opus-fixed rules carry over unless a section below says otherwise. Neither prereg decides anything about round 3.

## Question and the claims it supports

1. **Forced delivery (primary, scored).** At the moment a coding agent makes a mistake that a stored, applicable lesson describes, does showing that lesson's note, verbatim, make it less likely to make the same mistake again than showing nothing? The note is always the correct, pre-labeled lesson; the judge is not involved.
2. **Derived end-to-end figure (labeled "derived" and "upper bound").** Forced-delivery prevention times Plug's scored coverage, from round 3 (a8bf9ec, fixed). Its interval resamples **both** parts: branch points for the prevention, repositories for the coverage. It is an **upper bound** (it omits the wrong picks and mixes populations) and rests on an **independence assumption** [hypothesis]: a note's efficacy at the points where the judge speaks equals its efficacy at all points. The judge-gated direct arm that would have checked it is not run.
3. **Judge-gated direct arm: NOT RUN.** Declared before the freeze: at the measured capacity (about 60 own points; the judge needs a host that does not take the desktop GPU, and its CPU run took 142 to 206 s per call under Core's load) the arm cannot reach the 150-point, 50-speaking-points threshold, and the primary and derived figures do not need it. No judge-gated, `rag` or `ranker` branch is run. [measured]

## Design: branch points

- **Branch point.** The first moment in a run at which the agent executes a command that fails with a known key (key rule below). All arms continue from the same state: the same container filesystem and the same message history.
- **One snapshot method: `docker commit`.** For own prefixes the running prefix container is committed at the branch point. **Fidelity probe (frozen):** the SHA-256 of `git diff HEAD`, `git status --porcelain` and the sorted hashes of untracked files, taken in the prefix container just before the commit and again in every restored branch container before its first step. A mismatch voids the point, which is listed with its reason; a mismatching branch is never run anyway [established, by construction].
- **History replay is byte-identical:** each branch starts from a deep copy of the prefix's message list, with the arm's note appended under the failing observation and nothing else changed. The recorded reasoning text stays in the history objects as the model returned them; what the server renders from them is the same function of the history in every arm [established].
- **Sampling.** Temperature 0.6 with no seed, for the prefix and the branches alike, so the B branches of an arm are independent samples [hypothesis]. (PLUG-AGENT-1's temperature 0 would make every branch of an arm identical.) Reasoning low, 4,096 tokens per reply, step limit 75, wall cap 45 min.
- **Source of branch points: own `none` prefix runs only** on the pool's labeled tasks, on the laptop or the desktop Glimmer, each point's branches on one server. Plain-Glimmer runs of Core's are **not used**: their repositories have no nebius sessions, so no template-built lessons or frozen-prompt labels exist for them [established].
- **Arms at each branch point** [established]. `none` (nothing under the failing observation) and `forced` (the correct lesson's note appended verbatim under it). The correct lesson is the `applies`-labeled lesson whose key equals the failing key (the lowest lesson id if several). After the branch point every arm is silent: a branch differs from another only by the note at the point.
- **Branches per arm per point: B = 6** (Sizing), each a continuation of **W = 15 model calls**. A branch ends at W calls, at a submit, at three format errors in a row, at the step limit or at the wall cap, whichever comes first. **The wall cap (45 min per run or branch) is enforced by the agent's own limit and ends the branch like any exit** (tested in the harness: `TimeExceeded` is an interrupt that adds the exit message). **Early exits are not replaced:** a branch that ends early has its repeats counted up to its end and is kept; the exit status rates are reported per arm [established].
- **No `none2` arm.** The within-arm spread of the B branches at each point is the noise floor.

## Frozen rules carried over from PLUG-AGENT-1 [established]

- **Voids.** A branch lost to an infra or model_api error is requeued once. If a branch of either primary arm (`none`, `forced`) is lost twice, **the whole point is void** and listed with its reason; voids are reported per arm (the void record names the arm and branch index). Reaching the wall cap is not a void.
- Full config pinning: `results/plug-agent-2-config.json`. **The runner checks, before any run:** the whole config file's sha256 (given on its command line from this prereg's frozen header), the label file, label prompt, mistake-rule file and pool summary hashes it pins, and the served model (alias, byte size and parameter count of the pinned GGUF, read from the server's `/models`). The GGUF file's own sha256 is checked where the file lives, at server start, by the owner's launcher; the judge's `selection.json` and adapter hashes stay in the config as the provenance of round 3's coverage c. The config holds the GGUF sha256 and llama-server versions of both servers, temperature, W, B, limits, thresholds, `selection.json` and adapter hashes, the pool summary hash, the requeue cap, the Spark labeling cap, **the cutoff time (2026-11-01 06:00 PT) and the number of own branch points N (60)**, both settable by the coordinator until the freeze.
- **No interim looks.** The cutoff time and N are set in the config before the scored run. No analysis of scored branches is run before the cutoff; progress is monitored by counts of finished points and voids only.
- Scrubbed containers (base-commit history only); a failed scrub voids the point.
- Fixed point order: sha256 of `plug-agent-2:<instance_id>`; all branches of a point finish before the next point starts on that server.
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

**Primary (forced delivery).** Per point, the repeat share of the `forced` branches minus that of the `none` branches (6 each); the unit is the point, never the branch. The statistic is the mean over points of that difference d, tested by a **sign-flip permutation test on the mean** over points (100,000 flips, seed 0) with a BCa interval (10,000 resamples, seed 0) [established, declared now]. Points where both arms have the same share (for example 0 and 0) are ties: they stay in the mean and the sign-flip test, and their share is reported. **Expected tie share** [hypothesis]: with repeat shares of 0.4 and 0.2 per branch and 6 branches each, about 5% of points have equal shares; it rises quickly if the repeat rate is low, so the smoke's measured repeat share is used to restate it before the freeze.

**Frozen secondaries (no claims).** Repeat of any failure with the same error class as the branch point; any keyed failure in the window; exit status rates; steps to the next edit.

**Derived end-to-end figure.** E = c x d. **Coverage c is round 3's scored result (a8bf9ec), fixed now**: the judge's pick rate on applicable situations at the frozen threshold, 0.310 [measured, round 3], with its per-repository data for the bootstrap. The interval resamples points for d and repositories for c jointly (10,000 resamples, seed 0). **E is an UPPER BOUND, labeled "derived":** (1) forced delivery is a reminder after the agent has made the mistake, while c measures coverage over situation items from a different population; (2) E omits the cost of wrong notes (round 3: 5.3% wrong picks); (3) it assumes a note's efficacy at the points where the judge speaks equals its efficacy at all points [hypothesis]. The judge-gated arm that would have checked (3) is not run, so (3) stays untested.

**Gatekeeping.** The derived figure E is reported only if the primary succeeds (sign-flip p below 0.05 and the BCa interval excludes zero); otherwise only the primary is reported, with no E. No other estimate makes a claim.

## Smoke test and the one stop rule (frozen before the smoke test)

- 25 applies tasks chosen by sha256 order of `plug-agent-2-smoke:<instance_id>` from the 360, `none` arm, whole runs on the laptop Glimmer, 1 run each (2 each only if fewer than 10 runs hit a first known mistake), at temperature 0.6 like the scored runs. The first runs started before this was changed ran at temperature 0; their records carry no `temperature` field, they are counted in the readout and reported apart. **These 25 tasks are excluded from scoring.** [hypothesis]
- It reports: runs with a first known mistake, the repeat share **within W = 15 model calls of it** (the one definition, used by the stop rule, the branches and the sizing), the share of failures with no key, the top keys, steps and wall time per run, and the tie share the same counts imply.
- **Stop rule.** Go to the scored phase only if at least **10 smoke runs** hit a first known mistake **and** at least **30 percent** of those repeat it within W = 15, **and** the recomputed minimum detectable difference at **own points (source a) only** is at most 20 points.  Otherwise stop and the owner decides. More tasks are not the fallback. Only N may change after this rule is read out.
- **Early reading** (two finished runs): 4 failed commands, none with a key; the agent's mistakes are mostly generic interpreter failures [measured]. If the smoke confirms that keyed known mistakes are rare, the pool supplies too few branch points and the stop rule fires.

## Agent and infrastructure

- Plain Glimmer `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M` (GGUF sha256 `4cc57c0f...f60e`, same as the Strix), llama.cpp 0.8.0 build 11960 (commit 8642541b2) on the owner's laptop, 2 slots of 32k, flash attention, `--jinja`; reasoning low, 4,096 tokens per reply. Containers (mini-SWE-agent, scrubbed, no network) on the 5080 CPU; from Fri 08:00 PT the same GGUF is also served by the 5080 GPU through llama.cpp (build recorded in the config), a second server, each point's branches on one server. The bearer key comes from the environment and is never logged or written to a trajectory. No judge runs in this test; the 5080 GPU stays with Core. [established]
- **Speed** [measured, one task]: about 14 tok/s generation and about 115 tok/s uncached prompt with one stream; two streams run at 8 to 9 tok/s each (about 1.25 times one slot in total); about 21 s per model call; a 53-step run took 18 min. [established]
- Images are pulled just in time with their registry size checked first (limit 8 GB, disk floor 60 GB) and removed after the point's last branch. Long drivers run detached on the 5080 with a log, a done-file and resume.

## Sizing (stated before any scored run)

- **Capacity** [hypothesis, from measured speeds]: the laptop's two slots give about 214 model calls per hour. The desktop GPU serves the same GGUF at about 21 tok/s on one stream (Core's measure), about 250 calls per hour, in the window **Fri 08:00 to Sat 08:00 PT** (24 h) after Core's screening share. Branches of one point run on one server; the report states the server per point and the GGUF is the same on both.
- **Calls available** (about 40 laptop hours, 24 desktop hours): about 8,500 + 6,000 = **14,500 calls**. A point costs 12 branches x 15 calls = 180 calls plus its prefix (about 25 calls when it reaches a known mistake, a whole run of about 50 when it does not). **About 55 to 65 own points.**
- **Variance.** Binomial within a point at repeat shares 0.4 and 0.2 and B = 6 gives a variance of the paired difference of about 0.08; between-point variation of the effect adds 0.02 to 0.05. SD about 0.32 to 0.36.
- **Smallest detectable difference** (80% power, two-sided 5%): 2.8 x SD / sqrt(N): **about 12 to 13 points at N = 60 own points** [hypothesis]. B = 6 against B = 4 moves it by about 1 point; the between-point variation is the floor. "Pilot" is dropped from the wording only if the smoke's measured numbers keep it at 15 points or less at the N the pool can supply.
- The unknown that matters most is the number of points: it depends on how often the agent makes a keyed known mistake. The smoke measures it.

## Claim templates (fixed now)

1. **Forced delivery.** "In N branch points where Glimmer had just made a mistake that a stored lesson describes, showing that lesson's note verbatim cut repeats within 15 steps from X% to Y% (difference [estimate, BCa interval, sign-flip p]); the test detects differences of at least [MDE]." Labeled **forced delivery**.
2. **Derived end-to-end, upper bound.** "Plug shows the correct lesson in a fraction c of applicable situations [interval over repositories, round 3]; showing it cuts repeats by d points [interval over branch points]; so Plug would cut repeats by at most about c x d points [joint interval], omitting the cost of wrong notes." Labeled **derived** and **upper bound**, with the assumptions stated.

The report never says "the judge helps agents" and never uses speed-of-learning words.

## Not in this prereg

Any change to the judge, its thresholds or training; round 3's 40 scored repositories; Core's D2 scoring; solve rate.
