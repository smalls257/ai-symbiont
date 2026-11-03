"""The MCP tools that let the session's model curate a repository's lessons.

symbiont makes no model calls: it offers candidates and stores the verdicts the session's own
model returns. Each tool is one route of the local service; the service enforces consent and
which history the session may read.
"""

import json
from collections.abc import Mapping
from typing import Any

from symbiont.delivery.hooks import MUSE_CODE, MUSE_MARKER

AREAS_AND_TERMS = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "domain words and codes",
        },
        "areas": {"type": "array", "items": {"type": "string"}, "description": "path prefixes"},
    },
    "additionalProperties": False,
}


def _tool(
    name: str, route: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """A tool definition with the route it calls."""
    schema = {"type": "object", "properties": properties, "required": required}
    return {"name": name, "route": route, "description": description, "inputSchema": schema}


_ITEMS = {"type": "array", "items": {"type": "object"}}
_DESCRIPTIONS = {
    "add": (
        "Store lessons you wrote, in plain words, from notes, reports or docs the developer "
        "pointed you to. Each item: {text_in_plain_words, kind: "
        "mistake|rule|friction|correction, files?, source_label?, "
        "source_url? (https address of the pull request it came from), "
        "quote? (the reviewer's exact words that state the rule, copied verbatim, at most 300 "
        "characters, needs source_url), quote_role?: maintainer|reviewer, "
        "severity?: low|medium|high, applies_to?: {terms, areas}}."
    ),
    "cand": (
        "A batch of short past user messages that may be corrections of the agent. Judge "
        "each, then call symbiont_save_corrections. Pass running_in if asked."
    ),
    "savec": ("Save your judgments: [{candidate_id, is_correction, rule_in_plain_words}]."),
    "rev": (
        "A batch of pain points found by rules. Judge each as mistake, expected or noise, "
        "then call symbiont_save_reviews."
    ),
    "saver": (
        "Save your verdicts: [{id, verdict: mistake|expected|noise, rule_in_plain_words, "
        "title, merge_with?, applies_to?: {terms, areas}}]. Expected and noise silence the "
        "note."
    ),
    "focus": ("Save what the developer said symbiont should pay attention to in this repository."),
}
TOOLS = [
    _tool(
        "symbiont_add_lessons",
        "lessons/add",
        _DESCRIPTIONS["add"],
        {"lessons": _ITEMS},
        ["lessons"],
    ),
    _tool(
        "symbiont_correction_candidates",
        "corrections/candidates",
        _DESCRIPTIONS["cand"],
        {"running_in": {"type": "string", "enum": ["claude_code", "muse_code"]}},
        [],
    ),
    _tool(
        "symbiont_save_corrections",
        "corrections/save",
        _DESCRIPTIONS["savec"],
        {"corrections": _ITEMS},
        ["corrections"],
    ),
    _tool("symbiont_review_candidates", "reviews/candidates", _DESCRIPTIONS["rev"], {}, []),
    _tool(
        "symbiont_save_reviews",
        "reviews/save",
        _DESCRIPTIONS["saver"],
        {"reviews": _ITEMS},
        ["reviews"],
    ),
    _tool(
        "symbiont_set_focus",
        "focus",
        _DESCRIPTIONS["focus"],
        {
            "text": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        ["text"],
    ),
]
BY_NAME = {tool["name"]: tool for tool in TOOLS}


def listed_tools() -> list[dict[str, Any]]:
    """The tool definitions as MCP lists them (without the internal route)."""
    return [{key: value for key, value in tool.items() if key != "route"} for tool in TOOLS]


def route_and_body(
    name: str, arguments: dict[str, Any], environ: Mapping[str, str]
) -> tuple[str, dict[str, Any]]:
    """The service route and request body for a tool call; the harness is read from the host."""
    body = dict(arguments)
    if name == "symbiont_correction_candidates":
        body["running_in"] = _running_in(arguments, environ)
    return BY_NAME[name]["route"], body


def _running_in(arguments: dict[str, Any], environ: Mapping[str, str]) -> str:
    """Muse Code says so in its environment; otherwise the model must say which harness it is."""
    if MUSE_MARKER in environ:
        return MUSE_CODE
    chosen = arguments.get("running_in")
    if chosen not in ("claude_code", "muse_code"):
        raise ValueError("pass running_in: claude_code or muse_code")
    return str(chosen)


def as_text(reply: dict[str, Any]) -> str:
    """The service's reply as text for the model."""
    return json.dumps(reply, indent=1)
