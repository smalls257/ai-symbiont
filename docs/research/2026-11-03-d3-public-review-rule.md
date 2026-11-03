# A rule stated only in maintainer reviews of a public repository: result (D3, scored once, 2026-11-03)

Claim tags: [measured], [established], [hypothesis]. Row labels: floor, ceiling, reference or under test. Counts and ids: `results/d3-replication.json`. Preregs: `prereg/2026-11-03-d3-replication.md` (with `-amend1` and `-amend2`), `prereg/2026-11-03-d3-v3.md`, `prereg/2026-11-03-d3-v2.md` and `prereg/2026-11-03-d3-oracle-addendum.md`. Each is a copy of the file frozen in the run directory before the runs it covers; the sha256 of each frozen original is in the results file, and each copy ends with a note saying the only change is the claim tags the gate required. The copies were committed after the runs, so the git history does not show the freeze; the recorded hash and the freeze date in each file do.

## What was tested
The task is real. It is sqlglot, a public SQL translation library, and PR #7433 (Snowflake `POSITION` on binary arguments, translated to DuckDB), taken at its base commit. The contributor wrote a `.copy()` call and the reviewer asked for it to be removed.

The rule is "do not `.copy()` in generator code; the generator copies the whole syntax tree up front". It is stated only in maintainer reviews of earlier pull requests. The review on #7396 reads: "We don't need to copy here. This is taken care of in the top-level `generate` method of the generator." Others made the same point on #7394, #7433 and #7660. We searched the repository at the task's base commit and found the rule in no document and no code comment. Its CLAUDE.md even shows a `self.MY_TEMPLATE.copy()` template example, which points the other way [measured].

symbiont learned the rule through the product's `learn-from-prs` path. The model read the review text of three earlier pull requests (#7223, #7396 and #7289, all merged before the task's base commit; the task's own PR is excluded) and saved lessons. The stored lesson quotes the reviewer verbatim, because PR #74 made the product keep a reviewer's exact words and say them first. Model: Muse Spark.

The checker counts any added line under `sqlglot/` that contains `.copy(`. The PR had no tests, so we wrote them: 1 test that fails at the base commit and passes with the merged change, and 230 existing tests that must keep passing [measured].

## Result (replication, 10 fresh runs per arm)
| Row | Label | Runs that added any `.copy()` | Added `.copy()` lines in total | Runs passing the tests |
|---|---|---|---|---|
| Without symbiont | floor | 7 of 10 [measured] | 32 [measured] | 10 of 10 [measured] |
| With symbiont, verbatim quote | under test | 0 of 10 [measured] | 0 [measured] | 10 of 10 [measured] |

- **Primary, pre-registered:** runs with at least one added `.copy()`, compared by a two-sided Fisher exact test at alpha 0.05. 7 of 10 without symbiont against 0 of 10 with it gives p = 0.0031, significant, with symbiont lower [measured].
- **Secondary, descriptive:** without symbiont the added copies per run were 4, 0, 5, 0, 5, 2, 1, 8, 7, 0 (median 3, range 0 to 8); with it, 0 in every run. Runs with zero copies: 10 of 10 with, 3 of 10 without [measured].
- **Correctness:** all 20 runs pass the task's tests, so following the rule cost no correctness [measured].
- **Delivery:** in 10 of 10 runs with symbiont, the house-rules note fired at session start and a file rule fired once the model read `sqlglot/generators/duckdb.py`, carrying the reviewer's words from #7396 [measured].
- No run was invalid, none was re-run, and the v3 pilot, v2, oracle and viability runs are not pooled with these 20 [measured].
- Build `fbac29ec00dfe7c7ca4d19089d725cb0564c0875`, asserted before every run. Total spend about $17.6 of a $24 cap [measured].

## The arc
1. **D1 and D2 were nulls.** D1 looked for a repository convention that only a review comment states, in 17 repositories, and found no usable pair: the rules were already stated in the repository's own files, or the model could derive them from an engine installed in its sandbox [measured]. D2 tested a guard against calling a task done while its checks are red. It never fired in 3 of 3 sessions, so the design could not show a benefit: 2 of 3 green with the guard against 2 of 3 without [measured].
2. **D3 v1 was stopped by delivery bugs.** A pair was found and the lesson was learned, but the stored lesson was never delivered in a replay of 2 earlier runs. The model had filed it as a rule rather than a correction, and the file trigger returned before matching on a successful read or edit. No scored run was made [measured]. The fixes landed in PRs #69, #73 and #74.
3. **D3 v2, null with a paraphrase.** The model's own paraphrase of the rule ("do not copy properties inside a DuckDB generator sub-method") was delivered in 4 of 4 runs with symbiont. 3 of 4 with symbiont added a copy, against 2 of 4 without: a null on the primary [measured].
4. **Oracle row.** With the lesson set by hand to the maintainer's exact words, 1 of 4 runs added a copy. This is a reference row, not a product claim [measured]. It hinted that exact words might matter, no more than a pilot-sized hint at 4 runs [hypothesis].
5. **D3 v3 pilot.** With the verbatim quote learned through the product, 0 of 4 runs with symbiont added a copy against 3 of 4 without (Fisher exact p = 0.14, not significant), all 8 passing the tests [measured]. Reported on its own, not pooled.
6. **Replication.** The 10 against 10 above, with the primary test and the build frozen before the first run [measured].

## Caveats
- One repository, one rule, one task and one model (Muse Spark). Nothing here says the effect holds elsewhere [hypothesis].
- The tests are ours, because the PR had none. The prompt is our plain statement of the PR's purpose, with no solution in it.
- The checker counts any added `.copy(`, including a necessary one. None of the 20 runs needed one to pass the tests [measured].
- Not tested: rules whose reviewer wording is vague, other repositories, and a rule that conflicts with the visible code style.
- The difference between exact words and a paraphrase rests on small runs (4 per arm) from different builds. The replication compared no symbiont against the verbatim quote only; it did not vary the wording, so "exact words matter" stays a [hypothesis].
- Three runs ran in parallel in isolated Muse homes, so wall time is not a measure here.
