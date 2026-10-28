# eval: replay, scoring, spend and prereg guards

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/eval/`.

**Purpose.** Offline replay and AUROC/recall scores, the repeated-mistake metric, the spend guard (`budget`), the prereg check and the run orchestration.

**Violation prevented: Paper Tiger.** A fly learner that passes its tests but warns no better than plain counters would ship as a feature nobody benefits from. So the replay scores every learner on the same steps, the table cannot be rendered without the counters and similarity rows beside the fly row, and the live-learner choice is a rule fixed in the prereg, not a judgment made after the numbers.

## Invariants
- Replay is pure: sessions, references and history come in as arguments; run scripts load the data.
- The price table lives only in `budget.py`; every paid batch needs owner approval.
- `require_frozen` refuses a scored run unless the prereg is committed and unchanged; its sha256 goes into the results.
- Every result row has a role (floor, ceiling, reference, under test) and a claim tag.
- The grader never imports `delivery` or `service`; Route B and Act 1 reach `eval` only through `budget`.

## Imports
- May import: core, miner, records, store. Must not import: delivery, service.

## Commands
`uv run pytest tests/eval -q`

## Review focus
Could a tie be hidden? Is the split, seed and metric fixed in the prereg before this code runs on test data?
