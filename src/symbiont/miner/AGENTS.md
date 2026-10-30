# miner: pain points from records

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/miner/`.

**Purpose.** Pure rules that turn a chain of `Record`s into `PainPoint`s (reworked edit, failed command, loop, correction, blast radius, review flag).

**Violation prevented: Black Box and God Class.** A pain point nobody can trace is a warning nobody can trust, so every `PainPoint` cites the `RecordRef`s it came from, and a note can quote them verbatim. One signal per file under `signals/`; `mine.py` is the only place that lists them, so adding a signal is one line.

## Invariants
- Pure over records: no I/O, no clock. A chain is one developer's sessions on one repo in run order; parallel attempts are chains of one.
- Signals do not import each other; shared helpers (`commands`, `diffs`, `failing_tests`) are small and named by capability.
- A signal that cannot decide returns nothing; it never invents a pain point.

## Imports
- May import: `records`. Imported by: `core`, `store`, `eval`, `routeb`.
- Must not import: core, store, readers, service, delivery (airplane test, import-linter).

## Commands
`uv run pytest tests/miner -q`

## Review focus
Does the new signal have a test for the case it must stay silent on? Is the signature stable enough to count repeats?
