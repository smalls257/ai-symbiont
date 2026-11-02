"""What the developer said about each repository, kept beside the store.

Three states: given, declined, never asked; only GIVEN lets symbiont keep anything. It also
holds the notes the developer silenced and the one-time nightly announcement. One JSON file,
rewritten atomically: the service and the command line both touch it.
"""

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

REGISTRY_FILE = "repos.json"
Trouble = tuple[str, ...]  # the event log's spelling: (signal, *key)


class RepoStance(StrEnum):
    """The developer's answer for one repository; absence means they were never asked."""

    GIVEN = "given"
    DECLINED = "declined"


class RepoRegistryError(ValueError):
    """The registry file exists but is not a registry; the message names the file."""


class RepoRegistry:
    """Per-repository answers, silenced notes and announcements, read fresh on every call."""

    def __init__(self, data_dir: Path) -> None:
        """Keep the registry in `data_dir`; nothing is written until an answer is recorded."""
        self._path = data_dir / REGISTRY_FILE

    def stance(self, project: str) -> RepoStance | None:
        """The recorded answer, or None when the developer was never asked."""
        raw = self._entry(project).get("stance")
        return None if raw is None else RepoStance(raw)

    def record_stance(self, project: str, stance: RepoStance) -> None:
        """Remember the answer for `project`."""
        self._update(project, "stance", stance.value)

    def forget_project(self, project: str) -> None:
        """Drop everything remembered about `project`, so it is asked again."""
        document = self._document()
        document["projects"].pop(project, None)
        self._write(document)

    def muted(self, project: str) -> frozenset[Trouble]:
        """The kinds of trouble the developer silenced in `project`."""
        return frozenset(tuple(trouble) for trouble in self._entry(project).get("muted", []))

    def mute(self, project: str, trouble: Trouble) -> None:
        """Silence notes about `trouble` in `project`; idempotent."""
        silenced = sorted(self.muted(project) | {tuple(trouble)})
        self._update(project, "muted", [list(item) for item in silenced])

    def unmute(self, project: str, trouble: Trouble) -> None:
        """Let notes about `trouble` speak again."""
        silenced = sorted(self.muted(project) - {tuple(trouble)})
        self._update(project, "muted", [list(item) for item in silenced])

    def nightly_announced(self, project: str) -> bool:
        """Whether the developer was already told that nightly training is live here."""
        return bool(self._entry(project).get("nightly_announced", False))

    def announce_nightly(self, project: str) -> None:
        """Remember that the developer was told."""
        self._update(project, "nightly_announced", value=True)

    def _entry(self, project: str) -> dict[str, Any]:
        """The stored fields of one project; empty when it was never mentioned."""
        return self._document()["projects"].get(project, {})

    def _update(self, project: str, field: str, value: object) -> None:
        """Set one field of one project and write the file."""
        document = self._document()
        document["projects"].setdefault(project, {})[field] = value
        self._write(document)

    def _document(self) -> dict[str, Any]:
        """The file's JSON; a missing file is an empty registry, a malformed one raises."""
        if not self._path.exists():
            return {"projects": {}}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            _check_stances(document["projects"])
        except (ValueError, KeyError, TypeError) as exc:
            raise RepoRegistryError(f"{self._path} is not a repository registry") from exc
        return document

    def _write(self, document: dict[str, Any]) -> None:
        """Replace the file in one step, so a reader never sees half of it."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)


def _check_stances(projects: dict[str, Any]) -> None:
    """Raise ValueError or TypeError unless every recorded stance is one of the two answers."""
    for entry in projects.values():
        if "stance" in entry:
            RepoStance(entry["stance"])
