"""The words hooks share: the events a harness sends and how a note is worded and shown.

Kept apart from `hooks.py` so the installers and `hook_profiles.py` can name an event without
importing the code that reads profiles (which would be an import cycle).
"""

from enum import StrEnum


class HookEvent(StrEnum):
    """The harness events the hooks understand (day-1 G2 for Muse Code; Claude Code's docs)."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_LLM_CALL = "PreLLMCall"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"


class NoteStyle(StrEnum):
    """How a PostToolUse note is worded: plain prose, or a finding in the tool result's voice."""

    PLAIN = "plain"
    FINDING = "finding"


class NoteVisibility(StrEnum):
    """Who reads a note: the model alone, or the developer on screen as well."""

    MODEL_ONLY = "model-only"
    SHOWN = "shown"
