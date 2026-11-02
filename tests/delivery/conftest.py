"""Every delivery test starts with no real service to start and a throwaway data directory.

Failure guarded against: an offline-path test that spawns a real `symbiont serve` or writes the
developer's own ~/.symbiont (the hook starts a down service, which is what it must do in life).
"""

import pytest

from symbiont.delivery import hook_main, launch


@pytest.fixture(autouse=True)
def no_real_service_and_a_throwaway_home(monkeypatch, tmp_path):
    monkeypatch.setattr(hook_main, "DEFAULT_DATA_DIR", tmp_path / "symbiont-home")
    monkeypatch.setattr(launch, "start_service", lambda data_dir, port: None)
    monkeypatch.setattr(launch, "START_WAIT_S", 0.0)
