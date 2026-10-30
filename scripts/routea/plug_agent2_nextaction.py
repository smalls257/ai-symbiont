"""PLUG-AGENT-2 next-action test: does the agent's next command repeat the erroring one?

The matcher is frozen before any sampling: two commands are the same invocation when, after masking
paths, temp names, hex addresses and long numbers and collapsing whitespace, their first
HEAD_LENGTH characters are equal. The history sent to the model is the recorded history up to,
and excluding, the erroring turn, with only the wire fields. Pure.
"""

import json
from collections.abc import Mapping, Sequence

from plug_agent2_errorline import HEX_ADDRESS, LONG_NUMBER, PATH, SPACES, TEMP_NAME

HEAD_LENGTH = 120
WIRE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "name")


def normalized_invocation(command: str) -> str:
    """The command with volatile parts masked, spaces collapsed, cut at HEAD_LENGTH."""
    masked = command
    for pattern, mask in (
        (HEX_ADDRESS, "<hex>"),
        (TEMP_NAME, "<tmp>"),
        (PATH, "<path>"),
        (LONG_NUMBER, "<num>"),
    ):
        masked = pattern.sub(mask, masked)
    return SPACES.sub(" ", masked).strip()[:HEAD_LENGTH]


def same_invocation(command: str, erroring: str) -> bool:
    """The frozen matcher: an empty command never matches."""
    head = normalized_invocation(command)
    return bool(head) and head == normalized_invocation(erroring)


def wire_history(messages: Sequence[Mapping]) -> list[dict]:
    """The history as an OpenAI chat request carries it: known fields only, text content."""
    cleaned = []
    for message in messages:
        found = {key: message[key] for key in WIRE_FIELDS if message.get(key) is not None}
        if not isinstance(found.get("content", ""), str):
            raise TypeError("a history message has non-text content")
        cleaned.append(found)
    return cleaned


def first_command(reply: Mapping) -> str:
    """The first bash command of a chat reply's tool calls; empty when it issued none."""
    calls = (reply["choices"][0]["message"].get("tool_calls")) or []
    return json.loads(calls[0]["function"]["arguments"]).get("command", "") if calls else ""
