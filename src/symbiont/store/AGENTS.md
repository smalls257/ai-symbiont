# store: lessons and source pointers, never raw history

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/store/`.

**Purpose.** SQLite store of mined lessons and of where each project's history lives (`local.py`); mining that re-reads those logs through the readers (`mining.py`); the two training exports (`training.py`); the blast-radius reference scan (`references.py`).

**Violations prevented: Silent Fallback at the privacy and hold-out boundaries, and Infected Core by copied history.** Memory is the personal model's weights (owner decision 2026-10-28), so no record row is ever persisted: logs are re-read from where the harness wrote them each time mining runs, and dropped after. A store that quietly filtered private lessons would make a privacy bug look like "no history", and one that kept a scored task's lesson would let it train a scored model, so both guards raise.

## Invariants
- **No raw history is stored.** Tables: `sources` (project, reader, path pointers) and `lessons` (each with a bounded quote, resolution steps, `spark_safe`, source ids and task ids). Nothing else.
- Hold-out is checked at mining time (`remine`, via `records.holdout.refuse_held_out`) before any lesson is stored; a refused log is not registered. An id in neither spelling raises `UnrecognisedTaskIdError`.
- A registered log that is missing or unparseable raises naming the file; mining never skips it.
- `spark_view()` raises `SparkPrivacyViolationError` when any lesson of the project is private; it never filters.
- Two exports, two names: `lessons_for_memory_model` (Route A, Spark-reachable, through `spark_view()`) and `lessons_for_personal_model` (Route B, local, all lessons). No flag chooses between them.
- `forget_trained(project, manifest_path)` writes a manifest (lesson ids, source session ids, task ids, counts; no text) before deleting, never overwrites one, and deletes nothing if the write fails. `eval.training_manifest` checks it against the hold-out.
- Periphery: tests touch the disk and carry `@pytest.mark.periphery`.

## Imports
- May import: `records`, `miner`, `readers`. Imported by: service, eval, cli, scripts. Never by the pure core.

## Commands
`uv run pytest tests/store -q`

## Review focus
Does any new table or column hold record text beyond a lesson's bounded quote? Does any new read path bypass `spark_view()` for Spark-bound use? Is any new write path missing the mining-time hold-out check?
