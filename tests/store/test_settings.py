"""Correction finding is same-harness only unless the developer opts into crossing."""

import pytest

from symbiont.store.settings import (
    CorrectionSettings,
    SettingsFileError,
    read_correction_settings,
    write_correction_setting,
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
