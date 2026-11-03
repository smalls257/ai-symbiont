"""The Windows skip list names real test modules, so it cannot rot into an excuse.

Failure guarded against: a renamed or deleted module leaving a stale entry, or a new POSIX-only
test hiding behind a typo that ignores nothing.
"""

from pathlib import Path

import pytest

from posix_tooling import POSIX_TOOLING_TESTS

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("name", POSIX_TOOLING_TESTS)
def test_every_listed_module_exists(name):
    assert (HERE / name).is_file()
