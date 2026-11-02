"""Developer-set switches kept in `settings.json` beside the store.

Correction finding hands short excerpts of past messages to the session's model. It is allowed
only for history of the same harness the session runs in (Claude Code history in Claude Code,
Muse Code history in Muse Code) unless `cross_harness` is switched on.
"""

import json
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = "settings.json"
HARNESSES = ("claude_code", "muse_code")


class SettingsFileError(ValueError):
    """The settings file exists but is not a settings object; the message names it."""


@dataclass(frozen=True)
class CorrectionSettings:
    """Which histories may be shown to which session model."""

    claude_code: bool = True
    muse_code: bool = True
    cross_harness: bool = False

    def allows(self, history: str, running_in: str) -> bool:
        """Whether `history` may be shown to a session running in `running_in`."""
        if not getattr(self, history):
            return False
        return history == running_in or self.cross_harness


def read_correction_settings(data_dir: Path) -> CorrectionSettings:
    """The saved switches; defaults when the file is missing, an error when it is malformed."""
    path = data_dir / SETTINGS_FILE
    if not path.exists():
        return CorrectionSettings()
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("corrections", {})
        return CorrectionSettings(**{key: _flag(saved[key]) for key in saved})
    except (ValueError, TypeError, AttributeError) as exc:
        raise SettingsFileError(f"{path} is not a symbiont settings file: {exc}") from exc


def write_correction_setting(data_dir: Path, name: str, *, value: bool) -> CorrectionSettings:
    """Switch one setting and save; an unknown name raises SettingsFileError."""
    current = read_correction_settings(data_dir)
    if not hasattr(current, name):
        raise SettingsFileError(f"unknown correction setting {name!r}")
    updated = CorrectionSettings(**{**current.__dict__, name: value})
    data_dir.mkdir(parents=True, exist_ok=True)
    document = {"corrections": updated.__dict__}
    (data_dir / SETTINGS_FILE).write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    return updated


def _flag(value: object) -> bool:
    """A setting value that must be a real bool."""
    if not isinstance(value, bool):
        raise TypeError("a setting must be true or false")
    return value
