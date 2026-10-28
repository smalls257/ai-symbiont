# delivery: thin clients of one service

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/delivery/`.

**Purpose.** The MCP server (one tool, `recall(question)`), harness hooks (`symbiont hook <event>`), installers, and the mini-SWE-agent wrapper. Route A delivers the structured one-line note (what happened, how it was resolved, the check to run) before the matching action; Route B has Glimmer recall from its own weights when the classifier fires.

**Violation prevented: Silent Fallback and Distributed Monolith.** If the service is down, an empty note looks like "nothing to warn about", so every client prints a visible "symbiont offline" note and exits 0 so the harness is not blocked. Clients hold no logic: they forward to the localhost service, so each can be replaced alone.

## Invariants
- No learning, store or privacy logic here; the service owns it.
- Installers show a diff and ask before writing, are idempotent and reversible byte for byte, and never touch the user's global harness config.
- `recall` stays one plain question string.
- The plain (floor) arm of a run appends nothing.

## Imports
- Talks to `service` over localhost HTTP; imports no core, store or eval. Nothing imports delivery.

## Commands
`uv run pytest tests/delivery -q` (periphery tests, ephemeral port)

## Review focus
Offline path: is the note visible and the exit code 0? Does any client duplicate a decision the service should make?
