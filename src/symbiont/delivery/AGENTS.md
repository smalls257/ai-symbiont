# delivery: thin clients of one service

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/delivery/`.

**Purpose.** The MCP server (`recall(question)` plus the curation tools in `curation_tools.py`, each one service route), harness hooks (`symbiont hook <event>`), installers, and the mini-SWE-agent wrapper. Route A delivers the structured one-line note (what happened, how it was resolved, the check to run) before the matching action; Route B has Glimmer recall from its own weights when the classifier fires.

**Violation prevented: Silent Fallback and Distributed Monolith.** If the service is down, an empty note looks like "nothing to warn about", so every client prints a visible "symbiont offline" note and exits 0 so the harness is not blocked. Clients hold no logic: they forward to the localhost service, so each can be replaced alone. That includes rule relevance: whether a stored rule fires, and on which weighted signals (`fired_by`), is decided in `core/rule_relevance.py`; a client prints the note it is given and never re-matches.

## Invariants
- No learning, store or privacy logic here; the service owns it.
- Installers show a diff and ask before writing, are idempotent and reversible byte for byte, and never touch the user's global harness config.
- `recall` stays one plain question string.
- `open_page.py` opens a dashboard address with the desktop's own command (`open`, `xdg-open`) and returns False when it cannot, so `symbiont repo mine` can say so; only the CLI calls it, the service never opens a window. `launch.patient_call` is the `repo mine` variant of the reviving call: a developer waits for a cold start, a hook does not.
- A hook's human-facing `systemMessage` is a short headline from `headline.py` (at most 90 characters, cut at a word, `symbiont · <lead clause> (<where it came from>)`, or `symbiont · 2 notes: <lead> +1`), never the note. Why: Muse Code's TUI shows `systemMessage` only as one gray status line, truncated at terminal width, for 3-5 s, so the full note arrived cut mid-word (Black Box at the screen); Claude Code's is user-facing too. The model still gets the full, unchanged note in `additionalContext`; `--visibility model-only` still sends no `systemMessage`. Offline notes and service announcements stay whole (short, and the developer must read them). Provenance is read off the sentence (correction, history, rule); the hook has no dates and does not re-match.
- The Stop hook (`stop_hook.py`) only forwards to the service's `/reflect` and prints `{"decision":"block","reason":<question>}` (Claude Code and Muse Code both honor it, measured); it prints nothing when `stop_hook_active` is set, so the reflection turn cannot loop.
- The Stop hook asks `/stop/guard` first (Violation prevented: Silent Fallback): when the service says the last run of a check in this session failed and nothing passed it since, it prints `{"decision":"block","reason":<plain prose naming the check and its failure>}` once (plus a one-line `systemMessage` unless `--visibility model-only`) and does not ask for reflection on that stop. A Stop with `stop_hook_active` is never blocked by the guard; the one Stop that follows the guard's own block is handed to the reflection ask (`after_guard`), so neither loops.
- The plain (floor) arm of a run appends nothing.
- `hook_trace.py` is the hook's opt-in sensor (marker file or `SYMBIONT_HOOK_TRACE`); off by default; it holds raw payloads, so never commit a trace.
- The plugin hook (`hook_main.py`, script `symbiont-hook`) exits 0 on every path and prints a visible line for each failure; it imports no learner, store or numpy so it starts fast. `launch.py` starts a down service once (detached, `service.log` in the data directory) and does not retry for 30 s. `--harness auto` reads `MUSE_PLUGIN_ROOT` to tell Muse Code from Claude Code. The bundle is `plugin/symbiont/`; design in `docs/product/plugin.md`.

## Imports
- Talks to `service` over localhost HTTP; imports no core, store or eval. Nothing imports delivery.

## Commands
`uv run pytest tests/delivery -q` (periphery tests, ephemeral port)

## Review focus
Offline path: is the note visible and the exit code 0? Does any client duplicate a decision the service should make?
