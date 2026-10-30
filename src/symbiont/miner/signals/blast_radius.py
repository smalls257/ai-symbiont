"""Signal: blast radius, a change made without looking at the places it affects.

`references[path]` lists the files that import or name `path`; it is built
outside the core from a static scan of the repo checkout and passed in.
A pain point is an applied edit to `path` where, for one of its dependents:

- a later test run fails in the dependent itself, or in a test file that
  references the dependent (dialect.py <- duckdb.py <- test_duckdb.py), and
- the agent had not looked at the dependent before that failure: no view,
  no edit, no shell command naming it.

Key `(path, dependent)`, placed at the edit (the mistake), citing the edit
and the failing run. One pain point per (path, dependent) per call.
"""

from collections.abc import Iterator, Mapping, Sequence

from symbiont.miner.failing_tests import failing_test_files, same_file
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.records.schema import Kind, Record

References = Mapping[str, frozenset[str]]


Failures = list[tuple[Record, frozenset[str]]]


def find_blast_radius(session: Sequence[Record], references: References) -> list[PainPoint]:
    """Find edits whose unexamined dependents later broke; one per (path, dependent)."""
    failures = [(record, tests) for record in session if (tests := failing_test_files(record))]
    found: dict[tuple[str, str], PainPoint] = {}
    for change, path, dependent in _edited_dependents(session, references):
        if (path, dependent) in found:
            continue
        failure = _first_unwarned_failure(session, change, dependent, failures, references)
        if failure is not None:
            found[(path, dependent)] = _pain_point(path, dependent, change, failure)
    return list(found.values())


def _edited_dependents(
    session: Sequence[Record], references: References
) -> Iterator[tuple[Record, str, str]]:
    for change in filter(_applied_edit, session):
        for path in change.files:
            for dependent in sorted(references.get(path, ())):
                yield change, path, dependent


def _applied_edit(record: Record) -> bool:
    return record.kind == Kind.EDIT and record.exit_code != 1


def _first_unwarned_failure(
    session: Sequence[Record],
    change: Record,
    dependent: str,
    failures: Failures,
    references: References,
) -> Record | None:
    for failure, tests in failures:
        if failure.step <= change.step:
            continue
        if _breaks(dependent, tests, references) and not _looked_at(
            session, dependent, failure.step
        ):
            return failure
    return None


def _breaks(dependent: str, failing_tests: frozenset[str], references: References) -> bool:
    testing_it = {dependent, *references.get(dependent, ())}
    return any(same_file(test, tested) for test in failing_tests for tested in testing_it)


def _looked_at(session: Sequence[Record], path: str, before_step: int) -> bool:
    for record in session:
        if record.step >= before_step:
            return False
        if record.kind in (Kind.READ, Kind.EDIT) and any(
            same_file(name, path) for name in record.files
        ):
            return True
        if record.kind == Kind.COMMAND and path in (record.command or ""):
            return True
    return False


def _pain_point(path: str, dependent: str, change: Record, failure: Record) -> PainPoint:
    return PainPoint(
        signature=Signature(Signal.BLAST_RADIUS, (path, dependent)),
        session_id=change.session_id,
        step=change.step,
        record_refs=((change.session_id, change.step), (failure.session_id, failure.step)),
    )
