"""The settings.json hook block both harnesses read: event -> [{"hooks": [{"type": "command"}]}]."""

import json
from typing import Any

from symbiont.delivery.hooks import HookEvent, NoteStyle
from symbiont.delivery.install.transaction import InstallError, Transform

COMMAND_PREFIX = "symbiont hook "


def hook_command(event: HookEvent, harness: str, style: NoteStyle) -> str:
    """The shell command a harness runs for one event."""
    return f"{COMMAND_PREFIX}{event.value} --harness {harness} --notes {style.value}"


def merge_json(path: str, add: dict[str, Any]) -> Transform:
    """A transform that deep-merges `add` into the JSON file, keeping what is there."""

    def transform(original: str | None) -> str:
        current = _loaded(path, original)
        _merge(current, add)
        return json.dumps(current, indent=2) + "\n"

    return transform


def hooks_block(events: tuple[HookEvent, ...], harness: str, style: NoteStyle) -> dict[str, Any]:
    """The `hooks` settings entry that runs symbiont for each of `events`."""
    return {
        "hooks": {
            event.value: [
                {"hooks": [{"type": "command", "command": hook_command(event, harness, style)}]}
            ]
            for event in events
        }
    }


def _loaded(path: str, original: str | None) -> dict[str, Any]:
    if original is None or not original.strip():
        return {}
    try:
        loaded = json.loads(original)
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise InstallError(f"{path} must hold a JSON object")
    return loaded


def _merge(target: dict[str, Any], add: dict[str, Any]) -> None:
    for key, value in add.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        elif isinstance(value, list) and isinstance(target.get(key), list):
            target[key] = target[key] + [v for v in value if v not in target[key]]
        else:
            target[key] = value
