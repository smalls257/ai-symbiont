# scripts/evolve: the engine and file side of Evolve

See root CLAUDE.md for the repo rules. This file covers `scripts/evolve/`.

**Purpose.** Everything Evolve does that touches ViZDoom, files or a clock: the game player that turns a card and a case into a `GameResult`, the driver that resumes a run from `state.json`, and the progress exporter. The pure parts (card, fitness, selection, guards, the loop over a `Player`) live in `src/symbiont/act1/` and import nothing from here. Plays Freedoom via ViZDoom.

**Violation prevented: Infected Core and Silent Fallback.** The loop stays pure because the engine, the files and the clock are here. A model error during a move makes the game ungraded with its reason, never a loss or a win; a privacy refusal or a spend cap is not caught and stops the run.

## Invariants
- A training or validation game calls `levels.require_training(level)` before any engine call. A held-out level is played only with a frozen prereg handed in by the final-test runner.
- Run state (cards with text, lineage, per-game results) lives outside the repo in `~/symbiont-runs/evolve/<run>/state.json`, mode 0600, written atomically per game. Only counts, ids and labels go to `results/` and `dashboard/`.
- Siblings import each other by module name through `script_paths.py`; nothing under `src/` imports from here.
- No Spark, Glimmer or GPU call in this layer's tests: a fake reply function and a fake game stand in.

## Commands
`uv run pytest tests/scripts/test_evolve_*.py -q`

## Review focus
Is every exception that marks a game ungraded named, and does everything else propagate? Does any file written under `results/` or `dashboard/` hold card text?
