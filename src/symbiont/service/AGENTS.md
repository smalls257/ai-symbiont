# service: the localhost service and its event log

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/service/`.

**Purpose.** HTTP on localhost: `/observe` returns notes, `/recall` answers one question, `/learn` mines a new session log and updates the decider. `events.py` writes the event log.

**Violation prevented: Black Box.** Failure must be visible from outside, so every call appends a timestamped event (kind, project, latency, outcome) that the dashboard replays. A spark-bound recall that would return a private record answers 409 with "private history withheld from Spark" rather than an empty answer.

## Invariants
- `/recall` accepts exactly the plain-question payload; extra fields are rejected with 400.
- An empty store answers "no history for this project yet", never a fake note.
- State between sessions is the decider state, saved and restored; no shared mutable state across workers.
- Periphery: sockets, files and the clock live here and in tests marked `periphery`.

## Imports
- May import: core, store, miner, records. Must not import eval. Called by delivery over HTTP only.

## Commands
`uv run pytest tests/service -q`

## Review focus
Is each failure path an event and an explicit response? Any route that bypasses `spark_view()`?
