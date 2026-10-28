# eval: replay, scoring, spend and prereg guards

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/eval/`.

**Purpose.** Offline replay and AUROC/recall scores, the repeated-mistake metric, the spend guard (`budget`), the prereg check and the run orchestration.

**Violation prevented: Paper Tiger.** A fly learner that passes its tests but warns no better than plain counters would ship as a feature nobody benefits from. So the replay scores every learner on the same steps, the table cannot be rendered without the counters and similarity rows beside the fly row, and the live-learner choice is a rule fixed in the prereg, not a judgment made after the numbers.

## Invariants
- Replay is pure: sessions, references and history come in as arguments; run scripts load the data.
- The price table lives only in `budget.py`; every paid batch needs owner approval.
- `prereg.py` is pure (format check, `verify_frozen` over an injected git view); `prereg_git.py` is the periphery (`GitCli`, `require_frozen`, `run_provenance`). A scored runner takes `--scored --prereg <file>`; `require_frozen` raises `PreregNotFrozenError` unless the file is tracked with no working-tree or index diff (and, for an amendment, its original too). The commit (`freeze_commit`) and `prereg_sha256` go into the results, which say `run_label` scored or exploratory.
- `training_manifest.check_manifest_against_hold_out` proves, after lessons are deleted, that no held-out task trained a model; an unreadable manifest raises.
- Every result row has a role (floor, ceiling, reference, under test) and a claim tag.
- The grader never imports `delivery` or `service`; Route B and Act 1 reach `eval` only through `budget`.

## Imports
- May import: core, miner, records, store. Must not import: delivery, service.

## Commands
`uv run pytest tests/eval -q`

## Review focus
Could a tie be hidden? Is the split, seed and metric fixed in the prereg before this code runs on test data?
