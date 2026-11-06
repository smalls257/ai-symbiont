"""Developer-set switches kept in `settings.json` beside the store.

Correction finding hands short excerpts of past messages to the session's model. It is allowed
only for history of the same harness the session runs in (Claude Code history in Claude Code,
Muse Code history in Muse Code) unless `cross_harness` is switched on.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from symbiont.readers.harnesses import HARNESSES, Harness, UnknownHarnessError

SETTINGS_FILE = "settings.json"
CROSS_HARNESS = "cross_harness"


class SettingsFileError(ValueError):
    """The settings file exists but is not a settings object; the message names it."""


def _every_harness_on() -> dict[str, bool]:
    return {entry.id: True for entry in HARNESSES}


@dataclass(frozen=True)
class CorrectionSettings:
    """Which histories may be shown to which session model, one switch per registered harness."""

    enabled: Mapping[str, bool] = field(default_factory=_every_harness_on)
    cross_harness: bool = False

    def allows(self, history: str, running_in: str) -> bool:
        """Whether `history` may be shown to a session running in `running_in`."""
        if history not in self.enabled:
            raise UnknownHarnessError(f"no correction switch for harness {history!r}")
        if not self.enabled[history]:
            return False
        return history == running_in or self.cross_harness

    def as_saved(self) -> dict[str, bool]:
        """The flat object the settings file keeps: a switch per harness id, then cross_harness."""
        return {**self.enabled, CROSS_HARNESS: self.cross_harness}


def read_correction_settings(
    data_dir: Path, known: Sequence[Harness] = HARNESSES
) -> CorrectionSettings:
    """The saved switches; defaults when the file is missing, an error when it is malformed.

    A harness the file does not mention stays on; a key that is no harness id raises.
    """
    path = data_dir / SETTINGS_FILE
    defaults = {entry.id: True for entry in known}
    if not path.exists():
        return CorrectionSettings(defaults)
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("corrections", {})
        unknown = [key for key in saved if key not in defaults and key != CROSS_HARNESS]
        if unknown:
            raise ValueError(f"unknown correction setting {unknown[0]!r}")
        flags = {key: _flag(value) for key, value in saved.items()}
    except (ValueError, TypeError, AttributeError) as exc:
        raise SettingsFileError(f"{path} is not a symbiont settings file: {exc}") from exc
    cross = flags.pop(CROSS_HARNESS, False)
    return CorrectionSettings({**defaults, **flags}, cross)


@dataclass(frozen=True)
class DashboardSettings:
    """Whether `symbiont repo mine` opens the dashboard in the browser when it starts."""

    open_on_mine: bool = True


def read_dashboard_settings(data_dir: Path) -> DashboardSettings:
    """The saved switch; on when the file or the section is missing, an error when malformed."""
    path = data_dir / SETTINGS_FILE
    if not path.exists():
        return DashboardSettings()
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("dashboard", {})
        return DashboardSettings(**{key: _flag(saved[key]) for key in saved})
    except (ValueError, TypeError, AttributeError) as exc:
        raise SettingsFileError(f"{path} is not a symbiont settings file: {exc}") from exc


def write_dashboard_setting(data_dir: Path, *, open_on_mine: bool) -> DashboardSettings:
    """Switch whether mining opens the dashboard, keeping the other sections of the file."""
    updated = DashboardSettings(open_on_mine)
    _save_section(data_dir, "dashboard", updated.__dict__)
    return updated


def write_correction_setting(
    data_dir: Path, name: str, *, value: bool, known: Sequence[Harness] = HARNESSES
) -> CorrectionSettings:
    """Switch one setting and save; an unknown name raises SettingsFileError."""
    current = read_correction_settings(data_dir, known)
    if name == CROSS_HARNESS:
        updated = CorrectionSettings(current.enabled, value)
    elif name in current.enabled:
        updated = CorrectionSettings({**current.enabled, name: value}, current.cross_harness)
    else:
        raise SettingsFileError(f"unknown correction setting {name!r}")
    _save_section(data_dir, "corrections", updated.as_saved())
    return updated


MIN_SESSIONS_FLOOR = 1


@dataclass(frozen=True)
class MiningSettings:
    """How mining screens lessons: the sessions a trap must be seen in to become a lesson."""

    min_sessions: int = 2


def read_mining_settings(data_dir: Path) -> MiningSettings:
    """The saved mining settings; defaults when missing, an error when malformed."""
    path = data_dir / SETTINGS_FILE
    if not path.exists():
        return MiningSettings()
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("mining", {})
        return MiningSettings(**{key: _count(key, saved[key]) for key in saved})
    except (ValueError, TypeError, AttributeError) as exc:
        raise SettingsFileError(f"{path} is not a symbiont settings file: {exc}") from exc


def write_mining_setting(data_dir: Path, name: str, value: object) -> MiningSettings:
    """Set one mining setting and save; an unknown name or a bad value raises SettingsFileError."""
    current = read_mining_settings(data_dir)
    if not hasattr(current, name):
        raise SettingsFileError(f"unknown mining setting {name!r}")
    try:
        updated = MiningSettings(**{**current.__dict__, name: _count(name, value)})
    except (ValueError, TypeError) as exc:
        raise SettingsFileError(str(exc)) from exc
    _save_section(data_dir, "mining", updated.__dict__)
    return updated


def _count(name: str, value: object) -> int:
    """A setting that must be a whole number of at least MIN_SESSIONS_FLOOR (text is parsed)."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a whole number of at least {MIN_SESSIONS_FLOOR}")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None
    if number < MIN_SESSIONS_FLOOR:
        raise ValueError(f"{name} must be at least {MIN_SESSIONS_FLOOR}, got {number}")
    return number


def _save_section(data_dir: Path, section: str, values: Mapping[str, object]) -> None:
    """Write one section of the settings file, leaving the others as they were."""
    path = data_dir / SETTINGS_FILE
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    document[section] = values
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")


def _flag(value: object) -> bool:
    """A setting value that must be a real bool."""
    if not isinstance(value, bool):
        raise TypeError("a setting must be true or false")
    return value
