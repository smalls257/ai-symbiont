# examples: synthetic repositories for the reproduction kit

See root CLAUDE.md for the repo rules. This file covers `examples/`.

**Purpose.** Small, hand-written repositories that the "see it work" demo (`scripts/reproduce/see_it_work.sh`) copies to a temp directory. Nothing here is real customer or personal data.

**Violation prevented: Paper Tiger.** A demo whose repository is private or unavailable cannot be reproduced by a judge, so the repository ships with the code. Its tests fail on purpose (the designed trouble); the root `pytest` never collects them (`testpaths = ["tests"]`).

## Invariants
- Synthetic and hand-written. No dataset rows, transcripts, hostnames, paths or names of real people.
- The failing tests state the rule they enforce in their assertion messages, and the repository documents the rule (`examples/ledger/docs/currencies.md`).
- Nothing in `src/` imports from `examples/`.

## Review focus
Does a change make the designed failures pass, or change what `pytest -q -k <task>` prints? The demo's expected output depends on both.
