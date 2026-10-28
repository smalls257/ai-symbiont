# store: local records and pain points, with two guards

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/store/`.

**Purpose.** SQLite store of mined pain points (each with its own short quote and privacy flag) and failed-command resolutions; the only persistence the rest of the system sees. It keeps no raw history: the miner re-reads harness logs at the source, and lessons are training data only, deleted after training.

**Violation prevented: Silent Fallback at the privacy and hold-out boundaries.** A store that quietly filtered private records would make a privacy bug look like "no history", and one that accepted a scored task's trajectory would let `recall` surface a near-gold patch. So both guards raise: `add_records(..., held_out=...)` requires the held-out ids and raises `HoldOutViolationError`; `spark_view()` raises `SparkPrivacyViolationError`.

## Invariants
- The held-out set is a required argument, stated per batch; an id in neither spelling raises `UnrecognisedTaskIdError`.
- Any read that would return a `spark_safe=False` record, or a pain point citing one, raises from `spark_view()`.
- Hold-out is checked at mining time, before a lesson is kept; nothing raw is stored.
- The schema is the `records` contract; no other module reads the database file.
- Periphery: tests touch the disk and carry `@pytest.mark.periphery`.

## Imports
- May import: `records`, `miner`. Imported by: service, eval, routeb, scripts. Never by the pure core.

## Commands
`uv run pytest tests/store -q`

## Review focus
Does any new read path bypass `spark_view()`? Is any new write path missing the hold-out argument?
