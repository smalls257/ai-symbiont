# tests: the first caller of every public surface

See root CLAUDE.md for the repo rules. This file covers `tests/`.

**Purpose.** Prove behavior and hold the boundaries. The tree mirrors `src/`; `tests/gates/` tests the quality gates themselves.

**Violation prevented: Paper Tiger and Infected Core.** A suite that collected nothing is green, so the count floor and zero skips are gated. A unit test that needs a network is a core with an infected dependency, so `conftest.py` makes any socket call from an unmarked test raise `AirplaneViolationError`.

## Invariants
- Unmarked tests run in airplane mode. Anything touching network, disk or clock carries `@pytest.mark.periphery`: a classification, not an exemption.
- Zero skips. A test that cannot run is fixed or deleted; the floor in `scripts/gates/test-floor.txt` only goes up.
- Fixtures under `tests/fixtures/` are synthetic, hand-written, small. Semgrep fixtures mark each expected hit with `# expect: <rule-id>`.
- `import_rules.py` and `.importlinter` must agree.
- Functions at most 60 lines of code, files at most 600 lines.

## Commands
`uv run pytest -q` (about 45 seconds for the whole suite; the pre-commit hook runs only the tests of the packages a commit touches). Boundary tests: `uv run pytest tests/test_boundaries.py -q`.

## Review focus
Does the test fail for the right reason? Does a new test assert behavior, not that a mock was called?
