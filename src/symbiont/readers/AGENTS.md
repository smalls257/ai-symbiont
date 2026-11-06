# readers: one file per harness

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/readers/`.

**Purpose.** Turn one harness's logs into `Iterator[Record]`. A new harness is one new file, one `READERS` line, and one `Harness` entry in `harnesses.py` (id, label, env markers, stop cadence, how to find its session logs). Detection, discovery, settings keys and user-facing labels all read that registry; no other file branches on a harness id.

**Violation prevented: Silent Fallback.** A reader that skips a line it cannot parse trains on less and says nothing. A malformed or unknown-version line raises `ReadError` naming the file and line; the wizard names the file and asks the developer.

## Invariants
- Never skip, guess or default a field silently: unreported means `None`.
- Keep the observation as `raw` beside the action, so a failed command and its error text travel together.
- Readers do not import each other's internals; shared types live in `records` and `readers/errors.py`.
- Fixtures under `tests/fixtures/` are synthetic and hand-written, never dataset rows.

- `muse_code.py` reads `session.jsonl` from Muse Code's store (shape from its `read-session` skill); `session_logs` finds a workspace's main logs, never the subagent ones. Tests build synthetic lines; no real session is ever read in development.

## Imports
- May import: `records`. Must not import: core, miner, store, service. `READERS` in `__init__.py` maps reader names to functions; `harnesses.py` is the harness registry (Muse Code first in detection order because it also sets `CLAUDE_PLUGIN_ROOT`). store, service, delivery and cli may import `harnesses`.

## Commands
`uv run pytest tests/readers -q`

## Review focus
Truncated JSONL, unknown harness version, a tool call with undecoded arguments: does each raise with file and line?
