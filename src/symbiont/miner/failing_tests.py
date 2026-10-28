"""Which test files a test run reports as failing, read from its output.

pytest names them in its summary (`FAILED tests/x.py::T::t`, `ERROR tests/x.py`);
unittest names the test's module (`FAIL: t (tests.x.T.t)`). Paths may be
absolute; compare them with `same_file`.
"""

import re

from symbiont.records.schema import Kind, Record

_PYTEST = re.compile(r"^(?:FAILED|ERROR) (\S+?\.py)(?:::|\s|$)", re.MULTILINE)
_UNITTEST = re.compile(r"^(?:FAIL|ERROR): \w+ \(([\w.]+)\)", re.MULTILINE)


def failing_test_files(record: Record) -> frozenset[str]:
    """Test files named as failing; empty when the record reports no failure."""
    if not _reports_failure(record):
        return frozenset()
    found = set(_PYTEST.findall(record.raw))
    found |= {_module_path(dotted) for dotted in _UNITTEST.findall(record.raw)}
    found.discard("")
    return frozenset(found)


def same_file(first: str, second: str) -> bool:
    """True when two paths name the same repo file, one possibly absolute."""
    return first == second or first.endswith("/" + second) or second.endswith("/" + first)


def _reports_failure(record: Record) -> bool:
    return record.kind in (Kind.COMMAND, Kind.TEST_RESULT) and record.exit_code not in (None, 0)


def _module_path(dotted: str) -> str:
    """Map `tests.dialects.test_duckdb.TestDuckDB.test_cast` to `tests/dialects/test_duckdb.py`.

    The module ends where the class name (capitalized) begins.
    """
    module = []
    for part in dotted.split("."):
        if part[:1].isupper():
            break
        module.append(part)
    return "/".join(module) + ".py" if module else ""
