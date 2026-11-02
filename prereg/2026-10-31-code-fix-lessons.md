# Pre-registration: code-fix lessons study on SWE-smith (FROZEN)

**FROZEN 2026-10-31.** Code pinned at commit c3c678e (this commit's parent); committed alone, header only, before any model scores any item and before any Spark call of this study. After the freeze nothing in the design, rule, data or thresholds changes; only a dated amendment may add hashes of files that cannot exist earlier.

Claim tags: [measured] = observed in our own run, [established] = known or by construction, [hypothesis] = a guess the run can support or refute. Every number below is [measured] or [established] as marked. This is a NEW study, not a replication of round 4: the lesson definition, the data and the ordering differ. Round 4 stays reported as is (its nightly arm: no claim).

## Question
On code-fix lessons mined from public SWE-smith agent runs, does the nightly per-repository judge cover more later recurrences than the agree rule, with a wrong-pick rate whose exact upper bound is below 5%? [hypothesis]

## Data and definitions
- **Source:** public SWE-smith trajectories (Hugging Face, SWE-bench/SWE-smith-trajectories, splits tool, xml, ticks). **Disclosed:** the bugs are synthetic and injected; the agent's mistakes are real.
- **Failure (inferred):** SWE-smith observations carry no exit code, so a code-running command (python, pytest, pip, tox, make, mypy, ruff, uv) counts as failed when its output names an error class (`lessons.error_line`).
- **Code-fix lesson (new definition):** a command failed, the agent then edited code (str_replace, insert or create), and the same command reran and passed. The lesson is template-built: the failing command, its error line, and the edited file path(s) (`edit <path>`); the judge reads it through the unchanged judge format (`plug_judge.pair_prompt`, `JUDGE_SYSTEM`).
- **Recurrence:** a later task of the same repository fails with the same exact key (shown command, error line) as a stored lesson. **Stand-in ordering:** SWE-smith tasks have no dates, so tasks are ordered by a seeded hash (seed 0, sha1 of seed:task) [established]; the first half is the history (lessons and training), the second half is scored against that fixed history store. Identical lessons merge [established]; lessons with the same key and a different fix stay twins and count as one right answer (as in round 4).
- **Negatives:** later failures in the scored half with no exact or loose key match in the store, as many as positives per repository, chosen by a seeded hash. Items are built with the round 4 builder (`plug_r4_primary`): 60-lesson prompts, seeded cross-repository distractors [established].
- **Repositories (rule fixed before looking at outcomes):** non-excluded repositories ranked by scored-half positives, the smallest set of at least two reaching 450 positives [established], at most four [established]: pydantic/pydantic (237 recurrences) and getmoto/moto (225) [measured].
- **Exclusions:** no repository of the nebius/SWE-rebench pools used in rounds 1 to 4 (846 names [measured], `results/plug-r4-smith-exclusions.json`, matched by repository name) and no Core or Plug-in-the-loop repository (sqlglot, django) [measured]. Of 129 SWE-smith repositories, 34 overlapped with the pools.

## Arms and fixed settings (nothing is refit on this data)
- **Judge alone:** the round 3 judge (three seeds, mean P(yes)) at its frozen threshold 0.99.
- **Agree rule:** the same judge with the ranker, round 4's fitted point (`results/plug-r4-selection.json`: ranker score at least 10.0 and judge P(yes) at least 0.96).
- **Nightly arm:** one adapter per repository, trained from the general judge (round 4's base) on the history half only, round 4's recipe: Spark-invented situations (12 per lesson), Spark-labeled history pairs, near-misses from round 3 validation mistakes only, the round 3 judge's misses counted twice, balanced yes/no, 25% round 3 replay and 15% habit rows, read at strength 1.0, with round 4's rule (`results/plug-r4-selection-nightly.json`: judge threshold 0.98, no ranker cut). Scale differences from round 4, disclosed: at most 150 lessons and 60 labeled pairs per repository [established] (seeded by hash, history only).
- Spark sees only template-built lesson text and public trajectory text (the Contributor tier through `symbiont.egress`, laptop ledger cap 30 dollars, run cap 3 dollars per job [established]).

## Items, size and power [established, by calculation]
- 924 items: 462 recurrences and 462 negatives, 231 and 231 per repository sized by the rule above [measured].
- **Precision criterion, fixed now:** the exact Clopper-Pearson 95% upper bound of the wrong-pick rate over all 924 items must be below 0.05, round 4's bar. Wrong pick = a lesson answered that is not right, over all items. [established]
- **Power:** if the true wrong rate equals round 4's point estimate (15 of 501, 2.99%), the bound passes when at most 33 of 924 answers are wrong, which has probability 0.869 (at least 0.80) [established].

## Decision rule
- **Primary:** the nightly arm against the agree rule (the fair reference), per-cluster mean coverage over recurrences. **Clusters are tasks**, not repositories (two repositories cannot be clustered); the interval is the percentile bootstrap over tasks, 10,000 resamples, seed 0 [established]. "Better" requires the interval above zero, a mean gain of at least 0.05, AND the exact upper bound below 0.05; otherwise the numbers are reported with no claim.
- **Secondary:** agree rule against judge alone, same interval; exact bounds printed for every arm. The pre-registered bootstrap bound is also printed.
- **Refusals:** the runner checks the file, adapter and selection hashes (`results/plug-r4-smith-pins.json`); any missing score, repository or mismatch stops the run, nothing is read as silence.

## Limits
Two repositories from one benchmark, synthetic bugs, inferred failures, a stand-in ordering with no real time, a new lesson definition, round 4 thresholds applied to a different distribution, and winner's curse is not an issue for the thresholds (nothing is fitted here) but the recipe itself came from validation on round 3's repositories. A positive result would support the nightly arm on this kind of data only.

## Run
One detached script (`scripts/routea/plug_r4_smith_run.sh`) on the laptop with GPU stages on the 5080 (shared with Glimmer: it waits for 6 GB of free GPU memory [established] and never evicts anything). Estimated 2 to 3 hours of wall clock [hypothesis], cutoff Sun 2026-11-01 18:00.
