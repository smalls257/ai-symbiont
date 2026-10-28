# service: the localhost service and its event log

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/service/`.

**Purpose.** HTTP on localhost: `/observe` returns notes, `/recall` answers one question from stored lessons, `/learn` registers a harness log (`reader`, `session_log_path`, `project`), re-mines the project from all its logs and updates the decider. `events.py` writes the event log.

**Violation prevented: Black Box.** Failure must be visible from outside, so every call appends a timestamped event (kind, project, latency, outcome) that the dashboard replays. A spark-bound recall that would return a private record answers 409 with "private history withheld from Spark" rather than an empty answer.

## Invariants
- Route A (`--warner`, `--memory-url`, `--memory-dir`): the logistic warner decides per step, option A (`core/note_rules`: boundary steps, 2 notes per session, none in the 5 steps after one) rations, and the loopback memory model (`memory_model.py`, `Endpoint.LOCAL_MEMORY_MODEL`) writes the one line. An unusable reply answers 503, which the hook shows as "symbiont offline". Only projects named in the adapter's manifests are answered by the model; the event log carries prompt and note sizes and milliseconds, never the prompt.
- `/recall` accepts exactly the plain-question payload; extra fields are rejected with 400.
- An empty store answers "no history for this project yet", never a fake note.
- No raw history: notes and recall answers come from lessons (what happened, how it was resolved, the check to run); `/observe` has no stored records to recall from.
- A Spark-bound note must rest only on lessons the Spark view returned (under the user's own-history consent, read from `consent.json` at start); anything else answers 409.
- A Spark-bound call may use the memory model only when its adapter's recorded provenance (`adapter.json`, written by `train_memory.py` after a successful run) is `public`, or `own_history_with_consent` while consent is still given; `personal` or a missing record answers 409. Spark-bound answers and notes are scrubbed of credentials. Consent is read once at start: a withdrawal (`symbiont consent withdraw`) applies when the service restarts, not before.
- State between sessions is the decider state, saved and restored; no shared mutable state across workers.
- Periphery: sockets, files and the clock live here and in tests marked `periphery`.

## Imports
- May import: core, store, miner, records, readers, and `egress` for the memory model (Route A). Must not import eval. Called by delivery over HTTP only.

## Commands
`uv run pytest tests/service -q`

## Review focus
Is each failure path an event and an explicit response? Any route that bypasses `spark_view()`?
