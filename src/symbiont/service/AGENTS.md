# service: the localhost service and its event log

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/service/`.

**Purpose.** HTTP on localhost: `/observe` returns notes, `/recall` answers one question from stored lessons, `/learn` registers a harness log (`reader`, `session_log_path`, `project`), re-mines the project from all its logs and updates the decider. `events.py` writes the event log.

**Violation prevented: Black Box.** Failure must be visible from outside, so every call appends a timestamped event (kind, project, latency, outcome) that the dashboard replays. A spark-bound recall that would return a private record answers 409 with "private history withheld from Spark" rather than an empty answer.

## Invariants
- `/recall` accepts exactly the plain-question payload; extra fields are rejected with 400.
- An empty store answers "no history for this project yet", never a fake note.
- No raw history: notes and recall answers come from lessons (what happened, how it was resolved, the check to run); `/observe` has no stored records to recall from.
- A Spark-bound note must rest only on lessons the Spark view returned; anything else answers 409.
- State between sessions is the decider state, saved and restored; no shared mutable state across workers.
- Periphery: sockets, files and the clock live here and in tests marked `periphery`.

## Imports
- May import: core, store, miner, records, readers. Must not import eval. Called by delivery over HTTP only.

## Commands
`uv run pytest tests/service -q`

## Review focus
Is each failure path an event and an explicit response? Any route that bypasses `spark_view()`?
