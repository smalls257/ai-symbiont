# Corrected once, never repeated, for coding: result (synthetic, designed task, scored once, 2026-11-03)

Claim tags: [measured], [established], [hypothesis]. Row labels: floor, ceiling, reference or under test. Counts and ids: `results/corrected-once-v2.json`. Preregs: `prereg/2026-11-02-corrected-once.md` (v1) and `prereg/2026-11-03-corrected-once-v2.md` (v2). Both are byte-identical copies of the files frozen in the run directory; their sha256 values are in the results file, and the v2 file records its freeze at 2026-11-03 09:54 PST, before any v2 scored run. Both copies were committed to the repository after the runs, so the git history does not show the freeze; the recorded hash and timestamp do.

## What was tested
A hand-built toy ledger repository with three house rules that no file states: fees convert at today's rate and payouts at the charge's stored rate (R1), every posted entry gets an `audit.record` call (R2), and shares of money round in the house's favor (R3). In a teaching session the user stated each rule once, as a correction. symbiont stored the corrections, and eight new tasks (S1 to S8) were then run with and without it. A hidden checker scores each rule by behavior on probe scenarios. Model: Muse Spark.

## Result (v2, fixed build)
| Row | Label | Rule violations in 18 chances | Tasks with zero violations | Visible tests passing |
|---|---|---|---|---|
| Without symbiont | floor | 16 [measured] | 0 of 8 [measured] | 8 of 8 [measured] |
| With symbiont | under test | 0 [measured] | 8 of 8 [measured] | 8 of 8 [measured] |

- **Primary, pre-registered rule:** ON counts as better only if its total is below OFF. 0 is below 16, so the reading is better [measured]. No significance test was planned or run: 8 tasks, one run each.
- **By rule:** without symbiont R1 failed in 4 of 6 chances, R2 in 8 of 8, R3 in 4 of 4; with it none failed [measured].
- **Delivery confirmed** in run `v2-S1-on-1`: Muse's session log holds a developer-role context block at session start with the house rules, the service held back the older contradicting lesson as out of date, and the agent called `audit.record` [measured].
- **Where the rule has a different shape** (S5, S6, S8: audit only, or a payout instead of a fee) the agent also complied in every case [measured].
- Spend for v1 and v2 together was about $1.45 against a cap of $8 [measured].

## Caveats
- Synthetic, designed task: a toy repository and hand-written rules, built by us. It shows the delivery path works; it says nothing about real repositories [hypothesis].
- One model (Muse Spark), 8 tasks, one run per task per arm. A pilot-sized signal, no significance claim [measured].
- The corrections were scripted by us in the teaching session, and each states its rule as a complete sentence. The note carries those sentences nearly verbatim, so this shows the agent keeps a rule it was told, not that it can infer one.
- The without-symbiont arm broke 16 of 18 chances. The rules are not guessable from the code, which was checked before the freeze (a first rule set was too guessable and was replaced).
- v1 and v2 without-symbiont rows are different samples, so the v1 to v2 change is not a paired comparison.
- The v2 run reused the frozen v1 teaching store, wrong lesson included, instead of mining again. That keeps the lessons constant and changes only the build.

## The v1 stop
v1 ran on the earlier build and was stopped by the owner at 12 of 24 scored runs, with no verdict. On its first four tasks: 9 violations without symbiont, 7 with it, in 11 chances, and 0 of 4 tasks clean in every arm [measured]. Two delivery bugs explained it:
1. Correction lessons with no trigger terms never fired. The audit and rounding corrections did not appear at prompt time, so R2 never improved [measured].
2. A reflection written at the end of the first teaching turn, before the corrections, said the opposite of the fee-rate correction. It fired on S1 and made that task worse (3 violations with symbiont, 2 without) [measured].
Both were fixed in PR #69, which v2 includes (build `f7cd3353cdfbee9125dc98bf861bb6f8cd23950d`). Extra runs that finished past S4 before the stop arrived are not part of the 12 and carry no verdict.

## TODO (coordinator): D3, the public sqlglot test
TODO: D3 is still running. The coordinator adds its result and tags here; nothing is claimed about it until then.
