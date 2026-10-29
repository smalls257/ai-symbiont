# Amendment 1 to the Plug a2 prereg: row keys for the results gate

**FROZEN 2026-10-29.** Committed before `results/l2l-a2.json` is written from the scored output. It changes no data, split, pairing, recipe, seed, scorer, metric, label or decision rule.

Amends: prereg/2026-10-29-l2l-a2.md

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## What failed

The scored run ran once at the freeze commit 24881aa, and `plug.py check` recorded that commit as its `code_commit` [measured]. The run wrote its rows with the keys `row` and `label`. The repository's results gate (QG-SCI-03, `scripts/gates/check_results.py`) needs each row to name its `role` as one of floor, ceiling, reference or under_test, so it refused the file [measured]. The gate has no `control` role.

## What changes

`scripts/routea/plug_results_roles.py` copies the scored output and adds two keys to each row: `arm` (the row's name) and `role` (floor, reference and under_test unchanged; the two wrong-lesson rows, labeled `control`, take role `reference` and keep `label: control`). It also adds `scored_output_sha256`, the sha256 of the untouched scored output, which is kept beside the run's other local outputs [established]. No number is recomputed, so the scores, decisions and report sentence are the scored run's own [established]. Rescoring with changed code would break the code pin, and the prereg allows one scoring pass.
