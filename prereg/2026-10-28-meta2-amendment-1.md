# Amendment 1 to the META2 prereg

**FROZEN 2026-10-28.** Committed before the re-run.

Amends: prereg/2026-10-28-meta2.md

Claim tags: [measured] = observed in our own run, [established] = known from the literature or true by construction, [hypothesis] = a guess the run can support or refute.

## What failed

The first scored run (code `9c9b8ed`, 2026-10-28 19:19) passed the frozen-prereg and settings-sha checks. It then built the held-out episodes, which is labels only, and crashed when it forked its scoring workers [measured]. A macOS fork-safety check aborted a forked child: Objective-C runtime initialization was in progress in another thread at `fork()`, and the pool raised `BrokenProcessPool`.

No risk, threshold count, value or table was computed or written. `results/meta2.json` does not exist from that run, and no held-out label summary was opened [established].

## What changes

Only the command's environment. The re-run sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`, the documented macOS switch for this abort, and passes this amendment as `--prereg`, so `run_provenance` checks the chain back to the original.

Nothing else changes: not the code, data, split, seed, labels, prices, budget, cooldown, windows, thresholds, starts, metric, hypotheses or decision rule. The held-out episodes are rebuilt deterministically by the same step [established].

`results/meta2.json` will record this amendment as `prereg` and its commit as `freeze_commit`. The code is that of the original freeze commit plus this file [established].

## Command

`OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES OMP_NUM_THREADS=1 uv run --with torch python scripts/offline/run_meta2.py score --scored --prereg prereg/2026-10-28-meta2-amendment-1.md --settings results/meta2-settings.json --episodes ~/symbiont-runs/meta2/episodes --data-dir ~/symbiont-runs/meta2/data --starts ~/symbiont-runs/meta2/starts --out results/meta2.json`
