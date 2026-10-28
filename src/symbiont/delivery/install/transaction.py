"""Reversible project-file edits: show a diff, ask, back up the original bytes, restore them.

Shape prevents a silent, irreversible edit of a developer's config: nothing is written
before `approve` sees the diff, and uninstall puts back the exact original bytes (or
removes a file the installer created). Nothing here reaches outside `project_dir`.
"""

import difflib
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

STATE_DIR = ".symbiont"

# Original text (None when the file is absent) to the text it should have.
Transform = Callable[[str | None], str]


class InstallOutcome(StrEnum):
    """What an install call did."""

    INSTALLED = "installed"
    ALREADY_INSTALLED = "already installed"
    DECLINED = "declined"


class InstallError(RuntimeError):
    """The install or uninstall cannot proceed; the message says why and which file."""


@dataclass(frozen=True)
class HarnessInstall:
    """A harness's name and, per project-relative file, how to add symbiont to it."""

    name: str
    edits: Mapping[str, Transform]


def install(
    spec: HarnessInstall, project_dir: Path, approve: Callable[[str], bool]
) -> InstallOutcome:
    """Apply `spec` after `approve` has seen the diff; a second call changes nothing."""
    state = project_dir / STATE_DIR / f"install-{spec.name}"
    manifest = _read_manifest(state)
    originals = _originals(spec, project_dir, state, manifest)
    wanted = {rel: edit(originals[rel]) for rel, edit in spec.edits.items()}
    current = {rel: _read(project_dir / rel) for rel in wanted}
    if all(current[rel] == wanted[rel] for rel in wanted):
        return InstallOutcome.ALREADY_INSTALLED
    _refuse_edited_since(manifest, current)
    if not approve(_diff(wanted, current)):
        return InstallOutcome.DECLINED
    if manifest is None:
        _save_backups(state, project_dir, spec)
    for rel, text in wanted.items():
        _write(project_dir / rel, text)
    _write_manifest(state, {rel: _digest(wanted[rel]) for rel in wanted})
    return InstallOutcome.INSTALLED


def uninstall(spec: HarnessInstall, project_dir: Path) -> None:
    """Restore every file to its original bytes; refuses if a file changed since install."""
    state = project_dir / STATE_DIR / f"install-{spec.name}"
    manifest = _read_manifest(state)
    if manifest is None:
        raise InstallError(f"{spec.name} is not installed in {project_dir}")
    for rel, digest in manifest.items():
        if _digest(_read(project_dir / rel)) != digest:
            raise InstallError(f"{rel} changed since install; restore it by hand from {state}")
    for rel in manifest:
        _restore(state, project_dir / rel, rel)
    _remove_tree(state)


def _refuse_edited_since(manifest: dict[str, str] | None, current: dict[str, str | None]) -> None:
    """Raise InstallError when an installed file no longer matches its recorded digest."""
    for rel, digest in (manifest or {}).items():
        if _digest(current[rel]) != digest:
            raise InstallError(
                f"{rel} changed since install; uninstall by hand before reinstalling"
            )


def _originals(
    spec: HarnessInstall, project_dir: Path, state: Path, manifest: dict[str, str] | None
) -> dict[str, str | None]:
    """Pre-install contents of each edited file: live on first install, saved backups after."""
    if manifest is None:
        return {rel: _read(project_dir / rel) for rel in spec.edits}
    return {rel: _read_backup(state, rel) for rel in spec.edits}


def _save_backups(state: Path, project_dir: Path, spec: HarnessInstall) -> None:
    """Copy each existing file the install will edit into the state directory."""
    for rel in spec.edits:
        original = (project_dir / rel).read_bytes() if (project_dir / rel).exists() else None
        target = state / "backup" / rel
        if original is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)


def _restore(state: Path, path: Path, rel: str) -> None:
    """Put the backed-up bytes back, or delete a file the install created."""
    backup = state / "backup" / rel
    if backup.exists():
        path.write_bytes(backup.read_bytes())
        return
    path.unlink(missing_ok=True)
    _prune_empty_parents(path.parent, stop=state.parent.parent)


def _read_backup(state: Path, rel: str) -> str | None:
    """A saved backup's text, or None when the file did not exist before install."""
    backup = state / "backup" / rel
    return backup.read_bytes().decode() if backup.exists() else None


def _read(path: Path) -> str | None:
    """The file's text, or None when absent."""
    return path.read_bytes().decode() if path.exists() else None


def _write(path: Path, text: str) -> None:
    """Write text, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


def _digest(text: str | None) -> str:
    """sha256 of the text, or `absent` for a missing file."""
    return "absent" if text is None else hashlib.sha256(text.encode()).hexdigest()


def _read_manifest(state: Path) -> dict[str, str] | None:
    """The recorded digests, or None when nothing is installed."""
    manifest = state / "manifest.json"
    if not manifest.exists():
        return None
    loaded: dict[str, str] = json.loads(manifest.read_text())
    return loaded


def _write_manifest(state: Path, digests: dict[str, str]) -> None:
    """Record the digests; the state directory ignores itself because backups may hold tokens."""
    state.mkdir(parents=True, exist_ok=True)
    (state / ".gitignore").write_text("*\n")  # backups may hold tokens from env blocks
    (state / "manifest.json").write_text(json.dumps(digests, indent=2))


def _diff(wanted: dict[str, str], current: dict[str, str | None]) -> str:
    """A unified diff of the wanted files against the current ones."""
    parts: list[str] = []
    for rel, text in wanted.items():
        before = (current[rel] or "").splitlines(keepends=True)
        after = text.splitlines(keepends=True)
        parts += difflib.unified_diff(before, after, f"a/{rel}", f"b/{rel}")
    return "".join(parts)


def _remove_tree(state: Path) -> None:
    """Delete the state directory and any parents the install left empty."""
    for item in sorted(state.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        item.rmdir() if item.is_dir() else item.unlink()
    state.rmdir()
    _prune_empty_parents(state.parent, stop=state.parent.parent)


def _prune_empty_parents(directory: Path, stop: Path) -> None:
    """Remove empty directories upward until `stop`."""
    while directory != stop and directory.exists() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent
