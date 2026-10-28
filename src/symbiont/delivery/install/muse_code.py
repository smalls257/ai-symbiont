"""Muse Code: hooks in the project's .muse/settings.json.

The hook block shape is measured (accepted by `-c hooks=<json>`, day-1 G2); the project
file path is not measured, so it is named here once.
"""

from symbiont.delivery.hooks import HookEvent, NoteStyle
from symbiont.delivery.install.hook_config import hooks_block, merge_json
from symbiont.delivery.install.transaction import HarnessInstall

HARNESS = "muse_code"
EVENTS = tuple(HookEvent)
SETTINGS = ".muse/settings.json"


def muse_code_install(style: NoteStyle) -> HarnessInstall:
    """Hooks for Muse Code in one project."""
    return HarnessInstall(
        HARNESS, {SETTINGS: merge_json(SETTINGS, hooks_block(EVENTS, HARNESS, style))}
    )
