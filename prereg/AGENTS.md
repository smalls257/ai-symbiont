# prereg: frozen pre-registrations

See root CLAUDE.md for the repo rules. This file covers `prereg/`.

**Purpose.** One dated file per scored run: question, split, seed, labels, metric, decision rule, estimated spend, row labels. Frozen and committed before the run.

**Violation prevented: Silent Fallback at the claim level (and Forensic Coding).** Without a prereg the hypothesis was free to move after the numbers, so a scored result looks measured but is not. The runner (`eval.require_frozen`) refuses a scored run unless the file is frozen, committed and unchanged; no hook can be the only defence because a script can be run directly.

## Invariants
- A freeze commit changes only the status header. After the freeze the file is never edited.
- A crash or bug fix after freezing is a new dated amendment file committed before the re-run, saying what failed and what changed. It cannot change the split, seed, labels, metric or rule.
- No test-split metric is computed before the freeze.
- The Act 2 prereg template freezes the warning budget (share of steps that may warn), precision at that budget and net benefit per 100 steps (true warnings minus c times false warnings) as primary and secondary metrics before Act 2 runs; see `2026-10-28-warning-budget-exploratory.md` for the definitions. Balanced accuracy alone is not enough: it lets each learner pick its own warning rate.
- Every claim is tagged measured, established or hypothesis; the guard hook denies writes to a frozen file.

## Commands
`uv run python scripts/gates/check_claims.py prereg/*.md`

## Review focus
Is the decision rule a rule (numbers, direction, tie-break), fixed before data? Does a draft smuggle in an OPEN placeholder?
