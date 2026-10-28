# demo_tasks: constructed demo trap tasks

See root CLAUDE.md for the repo rules. This file covers `demo_tasks/`.

**Purpose.** `ledgerline/` is a small original MIT repo with four deliberate bugs. `trap_tasks.toml` turns it into four constructed demo tasks, one image each (`symbiont-trap-1..4`, built from `Dockerfile`). Every task has a hidden test and one process trap that a single structured note (`lesson`: what happened, how it was resolved, the check to run) should prevent. They show the mechanism behind "same bug, two runs"; they are never a benchmark result, and scored claims stay on public tasks.

## Invariants
- Label: "constructed demo task", in the task file, in every row and on every image.
- `ledgerline/` is the buggy base state the agent sees. Fixes live only in `tasks/<n>/gold.patch`; hidden tests only in `tasks/<n>/hidden_test.patch`.
- One trap per image: `drop_paths` removes the other tasks' trap scaffolding (`tests/soak`, `tests/rates`).
- A task change is re-proved with `scripts/calibration/validate_traps.py`: no patch fails, the gold patch resolves, the naive action fails or times out.
- `ledgerline/_amount_grammar.py` is generated from `ledgerline/codegen/amount_grammar.py.tmpl`; regenerate it after a template edit (`python -m codegen.build_grammar` inside `ledgerline/`).

## Commands
Rows: `python scripts/calibration/trap_rows.py demo_tasks/trap_tasks.toml rows.json`. Images: `python build_trap_images.py rows.json demo_tasks/ledgerline demo_tasks/Dockerfile`. Proof: `python validate_traps.py rows.json validation.json`. Glimmer screen: `python screen_traps.py rows.json <out_dir> --runs 2`. The last three run on the Docker host next to `taskenv.py` and `run_calibration.py`.

## Review focus
Does the trap still bite after an edit (naive action fails), and is the hidden test still the only place the fix is checked?
