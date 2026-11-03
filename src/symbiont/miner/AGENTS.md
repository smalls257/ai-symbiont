# miner: pain points from records

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/miner/`.

**Purpose.** Pure rules that turn a chain of `Record`s into `PainPoint`s (reworked edit, failed command, loop, correction, blast radius, review flag), find what resolved each (`resolutions.py`, `changes.py`), and build `Lesson`s (`lessons.py`): a pain point with its own bounded quote, resolution steps and `spark_safe` flag, so nothing downstream needs the records.

**Violation prevented: Black Box and God Class.** A pain point nobody can trace is a warning nobody can trust, so every `PainPoint` cites the `RecordRef`s it came from, and a note can quote them verbatim. One signal per file under `signals/`; `mine.py` is the only place that lists them, so adding a signal is one line.

## Invariants
- Pure over records: no I/O, no clock. A chain is one developer's sessions on one repo in run order; parallel attempts are chains of one.
- Signals do not import each other; shared helpers (`commands`, `diffs`, `failing_tests`) are small and named by capability.
- A signal that cannot decide returns nothing; it never invents a pain point.
- A resolution is what the history shows or a stated reason, never a guess. A failed command's fix is what changed between the failure and the later pass of the same command (same program, subcommand and target): installs, configuration, edits to a file the failure names, or a different invocation. "The same command" means the same program, subcommand and target, or the same *check* (`same_check.py`): a later clean pass whose tool matches (wrappers like `uv run`, `python -m`, `npx`, `bundle exec` peeled; `go test`/`cargo test` keep their subcommand) and whose targets are absent (a broader run) or overlap the failed run's (equal, path prefix, same file stem). It is language-agnostic on purpose, never parses a runner's output, and is loose: it may over-propose a lesson, and the delivery-time judge (agree rule, nightly judge) filters those; a run narrower than the failure, a different tool or disjoint targets never match. Pass/fail is the exit code plus the generic piped-output detector. The same command passing unchanged is no fix; an edit to a file the failure never names is reported alongside, never as the fix.
- A lesson's `spark_safe` is computed from every record it quotes, never defaulted; a missing cited record raises `LookupError`.
- No raw history leaves mining: a lesson keeps a quote of at most `QUOTE_CHARS` characters, never whole records.

- **Failure evidence is kept, not summarized away (Silent Fallback).** `failure_excerpt.py` cuts the expected-versus-actual lines of a failed run (pytest `E   - / +`, jest `Expected/Received`, cargo `left/right`, go `got/want`) to at most `EXCERPT_CHARS` (300) on whole lines, scrubbed where cut (`credential_scrub.py`); a lesson carries them as `expected_vs_actual`. `pasted_failure.py` recognizes a failing run or a red-CI sentence pasted into a user turn; `correction.py` mines it as a correction keyed `(failing file, "the CI run failed at <check>")`, and the lesson quotes the CI output rather than the issue text before it. A runner it does not know yields nothing.
- `unfinished_check.py` answers "is a check still red in this session": the latest failed run of a check (a runner's own failure output or a known test/lint/type/build tool) with no later pass of the same check (`same_check.py` identity). It is what the Stop hook's done-on-red guard reads.

## Imports
- May import: `records`. Imported by: `core`, `store`, `eval`, `routeb`.
- Must not import: core, store, readers, service, delivery (airplane test, import-linter).

## Commands
`uv run pytest tests/miner -q`

## Review focus
Does the new signal have a test for the case it must stay silent on? Is the signature stable enough to count repeats?
