"""The FX tests run against the frozen rate snapshot named in CONTRIBUTING.md."""

import os
from pathlib import Path

import pytest
from ledgerline.fx import load_rates


@pytest.fixture
def rates():
    """The rate table of the snapshot named by LEDGERLINE_FIXTURES."""
    return load_rates(Path(os.environ["LEDGERLINE_FIXTURES"]))
