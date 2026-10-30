# act1: a model plays Freedoom via ViZDoom

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/act1/`.

**Purpose.** State to text for a language model, a strict move parser, scripted moves, and the episode runner. Say "plays Freedoom via ViZDoom"; never brand as Doom.

**Violation prevented: Silent Fallback.** A model that invents a move must be visible as an invalid reply, so parsing is strict: an unknown move raises `StrategyError`, a bad map raises `WadError`; nothing falls back to "explore". Every move is scripted and says so in its label.

## Invariants
- `wad`, `map_index`, `env_text`, `moves` are pure over bytes and plain data; `engine.py` (ViZDoom adapter), `episode.py`, `glimmer.py` and `setup_assets.py` touch the engine, network and disk (periphery).
- The Glimmer chat call is `glimmer.chat_reply`, which goes through `symbiont.egress` (`Endpoint.LOCAL_GLIMMER`); act1 opens no socket itself and logs no prompt text.
- ViZDoom is a dependency, never vendored. Freedoom assets are copied into gitignored `data/`; the BSD-3 notice ships beside them.
- No id Software assets. No speed-of-learning claims.

## Imports
- May import: records, core, `egress`, and `eval.budget` only. Must not import the grader or delivery/service.

## Commands
`uv run pytest tests/act1 -q`

## Review focus
Does each new engine call live in the periphery files? Is every reply path that cannot be parsed an error?
