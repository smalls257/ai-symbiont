"""A third harness needs only its entries.

Violation prevented: Distributed Monolith. The fake harness below is one `Harness` and one
`HookProfile`; nothing else in `src/` is touched, and every branch site must accept it.
"""

import argparse
from pathlib import Path

import pytest

from symbiont.delivery.curation_tools import route_and_body
from symbiont.delivery.hook_profiles import EchoPolicy, HookProfile, ProjectNaming, profile
from symbiont.delivery.install.transaction import HarnessInstall
from symbiont.readers.harnesses import HARNESSES, Harness, StopCadence, detect
from symbiont.service.mine_command import MineClient, mine_past_sessions
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import (
    CorrectionSettings,
    SettingsFileError,
    read_correction_settings,
    write_correction_setting,
)

pytestmark = pytest.mark.periphery

LOG = Path("/fixtures/fake-harness/session-1.log")


def _fake() -> Harness:
    return Harness(
        id="fake_code",
        label="Fake Code",
        reader="fake-code",
        env_markers=("FAKE_CODE_HOME",),
        stop_cadence=StopCadence.END_OF_SESSION,
        find_sessions=lambda repo_dir, environ, home: [LOG],
        sessions_live_in=lambda environ, home: home / ".fake" / "sessions",
        plugin_setup=(("fake", "plugin", "add", "symbiont"),),
    )


def _fake_profile() -> HookProfile:
    return HookProfile(
        harness_id="fake_code",
        edit_tools=frozenset({"fake_edit"}),
        shell_tools=frozenset({"fake_shell"}),
        read_tools=frozenset({"fake_read"}),
        shell_exit=lambda outcome: 0,
        echo=EchoPolicy.NONE,
        project_naming=ProjectNaming.CWD_NAME,
        install=lambda style: HarnessInstall("fake_code", {}),
    )


KNOWN = (*HARNESSES, _fake())


def test_the_fake_harness_is_detected_and_beats_nothing_else():
    assert detect({"FAKE_CODE_HOME": "/x"}, KNOWN).id == "fake_code"
    assert detect({"MUSE_PLUGIN_ROOT": "/x"}, KNOWN).id == "muse_code"


def test_its_profile_is_found_in_a_registry_that_holds_it():
    fake = _fake_profile()

    assert profile("fake_code", {"fake_code": fake}) is fake


def test_correction_settings_accept_it_and_save_it(tmp_path):
    settings = CorrectionSettings(enabled={h.id: True for h in KNOWN})
    assert settings.allows("fake_code", "fake_code") and not settings.allows(
        "fake_code", "muse_code"
    )

    write_correction_setting(tmp_path, "fake_code", value=False, known=KNOWN)

    saved = read_correction_settings(tmp_path, known=KNOWN)
    assert not saved.allows("fake_code", "fake_code")
    assert saved.allows("muse_code", "muse_code")
    with pytest.raises(SettingsFileError, match="fake_code"):
        read_correction_settings(tmp_path)  # the stock registry does not know it


def test_the_curation_running_in_check_accepts_it():
    _, body = route_and_body("symbiont_correction_candidates", {}, {"FAKE_CODE_HOME": "1"}, KNOWN)
    assert body["running_in"] == "fake_code"

    _, body = route_and_body(
        "symbiont_correction_candidates", {"running_in": "fake_code"}, {}, KNOWN
    )
    assert body["running_in"] == "fake_code"
    with pytest.raises(ValueError, match="fake_code"):
        route_and_body("symbiont_correction_candidates", {}, {}, KNOWN)


def test_past_session_discovery_asks_it_for_its_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Path.home() on Windows
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    RepoRegistry(tmp_path).record_stance("demo", RepoStance.GIVEN)
    asked: list[tuple[str, dict]] = []

    def ask(route, body, port):
        asked.append((route, body))
        return {
            "started": True,
            "state": "done",
            "lessons": 0,
            "error": "",
            "sessions_read": 1,
            "sessions_total": 1,
            "pain_points": 0,
        }

    args = argparse.Namespace(
        project="demo", repo_dir=tmp_path, port=1, data_dir=tmp_path, no_open=True
    )
    client = MineClient(ask, lambda url: True, lambda seconds: None)

    code = mine_past_sessions(args, RepoRegistry(tmp_path), client, KNOWN)

    assert code == 0
    assert ["fake-code", str(LOG)] in asked[0][1]["sources"]
