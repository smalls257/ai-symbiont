# records: the one contract

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/records/`.

**Purpose.** `Record` and `Provenance`: what every harness reader produces and everything after reads.

**Violation prevented: Distributed Monolith (and the Leaky Narrative of an untyped dict).** If readers, miner, store and core could pass loose dicts, a schema change would need edits in N places and every caller would read the producer's source. So the API is frozen dataclasses with JSONL in and out, and nothing else crosses the boundary.

## Invariants
- Records are frozen. `raw` keeps the original text unsummarised so any note can quote what happened.
- `Provenance.spark_safe` has no default: unknown privacy is never treated as shareable.
- `exit_code=None` means "not reported", never "succeeded".
- Task-id normalization lives here (`owner__repo-123` and `owner/repo#123` compare equal); an unrecognized id raises.
- Pure: no network, clock, files (callers pass file handles to `load_jsonl`/`dump_jsonl`).

## Imports
- May import: the standard library only.
- Imported by: every other package. It imports none of them (import-linter `layers` contract).

## Commands
`uv run pytest tests/records -q`

## Review focus
A new field needs a default or a reason it has none. Check that no reader or learner now needs a private name from here.
