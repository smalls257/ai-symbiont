# readers: one file per harness

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/readers/`.

**Purpose.** Turn one harness's logs into `Iterator[Record]`. A new harness is one new file plus one registry line.

**Violation prevented: Silent Fallback.** A reader that skips a line it cannot parse trains on less and says nothing. A malformed or unknown-version line raises `ReadError` naming the file and line; the wizard names the file and asks the developer.

## Invariants
- Never skip, guess or default a field silently: unreported means `None`.
- Keep the observation as `raw` beside the action, so a failed command and its error text travel together.
- Readers do not import each other's internals; shared types live in `records` and `readers/errors.py`.
- Fixtures under `tests/fixtures/` are synthetic and hand-written, never dataset rows.

## Imports
- May import: `records`. Must not import: core, miner, store, service. Registry by harness name in `__init__.py`.

## Commands
`uv run pytest tests/readers -q`

## Review focus
Truncated JSONL, unknown harness version, a tool call with undecoded arguments: does each raise with file and line?
