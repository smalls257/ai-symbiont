"""Turn an item and a reasoning strength into the chat messages Glimmer sees (pure over files).

Violation prevented: Leaky Narrative between arms. The two arms must differ in one line only, so
the system message is built by replacing that line and nothing else.
"""

from pathlib import Path
from typing import Any

from gate_client import BASH_TOOL, reasoning_line
from gate_items import trajectory

from symbiont.act1.episode import build_prompt

KEPT_FIELDS = ("role", "content", "tool_calls", "tool_call_id")


def doom_messages(item: dict[str, Any], strength: str) -> list[dict[str, Any]]:
    """Act 1's own first-decision prompt (no history) behind Act 1's reasoning line."""
    return [
        {"role": "system", "content": reasoning_line(strength)},
        {"role": "user", "content": build_prompt(item["observation"], [])},
    ]


def _with_strength(system_text: str, strength: str) -> str:
    first, _, rest = system_text.partition("\n")
    if not first.startswith("Reasoning strength:"):
        raise ValueError("trajectory system message has no reasoning line to replace")
    return f"{reasoning_line(strength)}\n{rest}"


def coding_messages(workdir: Path, item: dict[str, Any], strength: str) -> list[dict[str, Any]]:
    """The recorded conversation up to, not including, the real edit; reasoning line swapped."""
    recorded = trajectory(workdir, item["trajectory"])["messages"][: item["gold_index"]]
    messages = [{k: m[k] for k in KEPT_FIELDS if m.get(k) is not None} for m in recorded]
    messages[0]["content"] = _with_strength(messages[0]["content"], strength)
    return messages


def request_for(
    workdir: Path, item: dict[str, Any], strength: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """(messages, tools) for one item and arm."""
    if item["domain"] == "freedoom":
        return doom_messages(item, strength), None
    return coding_messages(workdir, item, strength), [BASH_TOOL]
