"""Correction finding is same-harness only unless the developer opts into crossing."""

import pytest

from symbiont.store.settings import (
    CorrectionSettings,
    SettingsFileError,
    read_correction_settings,
    read_dashboard_settings,
    write_correction_setting,
    write_dashboard_setting,
)

pytestmark = pytest.mark.periphery


def test_defaults_allow_each_harness_for_itself_and_never_across():
    settings = CorrectionSettings()

    assert settings.allows("muse_code", "muse_code") and settings.allows(
        "claude_code", "claude_code"
    )
    assert not settings.allows("muse_code", "claude_code")
    assert not settings.allows("claude_code", "muse_code")


def test_a_switch_is_saved_and_cross_harness_needs_its_own_opt_in(tmp_path):
    write_correction_setting(tmp_path, "muse_code", value=False)
    write_correction_setting(tmp_path, "cross_harness", value=True)

    settings = read_correction_settings(tmp_path)

    assert not settings.allows("muse_code", "muse_code")
    assert settings.allows("claude_code", "muse_code")


def test_a_malformed_or_unknown_setting_raises(tmp_path):
    (tmp_path / "settings.json").write_text('{"corrections": {"muse_code": "yes"}}')
    with pytest.raises(SettingsFileError, match="settings.json"):
        read_correction_settings(tmp_path)
    with pytest.raises(SettingsFileError, match="unknown"):
        write_correction_setting(tmp_path / "x", "nope", value=True)


def test_opening_the_dashboard_on_mine_is_on_until_switched_off_and_sections_do_not_clobber(
    tmp_path,
):
    assert read_dashboard_settings(tmp_path).open_on_mine is True

    write_correction_setting(tmp_path, "cross_harness", value=True)
    write_dashboard_setting(tmp_path, open_on_mine=False)
    write_correction_setting(tmp_path, "muse_code", value=False)

    assert read_dashboard_settings(tmp_path).open_on_mine is False
    assert read_correction_settings(tmp_path).cross_harness is True


def test_a_malformed_dashboard_setting_raises(tmp_path):
    (tmp_path / "settings.json").write_text('{"dashboard": {"open_on_mine": "no"}}')
    with pytest.raises(SettingsFileError, match="settings.json"):
        read_dashboard_settings(tmp_path)


# --- mining -------------------------------------------------------------------------------


def test_min_sessions_defaults_to_two_and_a_change_is_saved(tmp_path):
    from symbiont.store.settings import MiningSettings, read_mining_settings, write_mining_setting

    assert read_mining_settings(tmp_path) == MiningSettings(min_sessions=2)
    write_mining_setting(tmp_path, "min_sessions", "1")
    assert read_mining_settings(tmp_path).min_sessions == 1


@pytest.mark.parametrize("bad", ["0", "-3", "two", "1.5", True])
def test_min_sessions_below_one_or_not_a_whole_number_is_refused_by_name(tmp_path, bad):
    from symbiont.store.settings import read_mining_settings, write_mining_setting

    with pytest.raises(SettingsFileError, match="min_sessions"):
        write_mining_setting(tmp_path, "min_sessions", bad)
    assert read_mining_settings(tmp_path).min_sessions == 2


def test_an_unknown_mining_setting_is_refused_and_other_sections_survive(tmp_path):
    from symbiont.store.settings import write_mining_setting

    write_correction_setting(tmp_path, "cross_harness", value=True)
    with pytest.raises(SettingsFileError, match="knob"):
        write_mining_setting(tmp_path, "knob", 3)
    write_mining_setting(tmp_path, "min_sessions", 4)
    assert read_correction_settings(tmp_path).cross_harness is True
