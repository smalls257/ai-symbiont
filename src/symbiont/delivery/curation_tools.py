"""The MCP tools that let the session's model curate a repository's lessons.

symbiont makes no model calls: it offers candidates and stores the verdicts the session's own
model returns. Each tool is one route of the local service; the service enforces consent and
which history the session may read.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from symbiont.readers.harnesses import HARNESSES, Harness, detect

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
_HARNESS = {"running_in": {"type": "string", "enum": [entry.id for entry in HARNESSES]}}
# Tools whose route reads history, so the service must know which harness the session runs in.
_READS_HISTORY = frozenset(
    {
        "symbiont_correction_candidates",
        "symbiont_session_candidates",
        "symbiont_group_candidates",
        "symbiont_rule_candidates",
        "symbiont_save_rules",
        "symbiont_topic_candidates",
        "symbiont_save_topics",
    }
)
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
        "then call symbiont_save_reviews. Each carries what the user asked, what the agent "
        "meant to do, how often it happened and how it ended; use them to write the summary."
    ),
    "saver": (
        "Save your verdicts: [{id, verdict: mistake|expected|noise, rule_in_plain_words, "
        "title, summary, merge_with?, applies_to?: {terms, areas}}]. summary is two or three "
        "sentences: what the agent was trying to do, what went wrong, whether it was fixed, and "
        "whether this is worth keeping as a lesson. Expected and noise silence the note."
    ),
    "sess": (
        "A batch of digests of past sessions that have no summary yet, oldest first: what the "
        "developer asked, the files edited, failed commands, corrections and how the session "
        "ended (last_turns). Summarize each with your own judgment, not keyword rules, then "
        "call symbiont_save_session_summaries. Pass running_in if asked."
    ),
    "savesum": (
        "Save your summaries: [{session_id, goal (at most 12 words), outcome: "
        "done|partly|stuck|unclear (judge it from last_turns), friction (at most 10 words, or "
        "empty), noise (true for a session that was no real work)}]. Repeat the candidates and "
        "saves until none are left."
    ),
    "topcand": (
        "Every summarized session with its corrections, once enough are summarized (otherwise "
        "it says how many more are needed). Group them, then call symbiont_save_topics. If the "
        "answer has developer_names (was -> now), the developer renamed those topics or groups: "
        "keep their names. Pass running_in if asked."
    ),
    "savetop": (
        "Save the grouping: {topics: [{name (2 to 4 words), description, session_ids}], "
        "frictions: [{name (2 to 5 words), description, session_ids}], correction_groups: "
        "[{name (2 to 5 words, like 'Back to main and pull'), description, refs: "
        "[[session_id, step]]}]}. Every session must be in exactly one topic; an 'Other' topic is "
        "allowed. Split a topic that holds more than a quarter of the sessions. Pass running_in "
        "if asked."
    ),
    "groupcand": (
        "Up to 40 recurring pain-point groups that have no one-line verdict yet, each with its "
        "name, what happened, what fixed it, how often, and 3 example cards. Dataset history is "
        "refused; history the developer barred from this session is left out (see not_shown). "
        "Write one sentence per group, then call symbiont_save_group_verdicts. Pass running_in "
        "if asked."
    ),
    "savegroup": (
        "Save your verdicts: [{key (from the candidates), sentence}]. One line, at most 220 "
        "characters, starting 'Worth a look: ' (what is going on and what would stop it), "
        "'Fixed in practice: ' or 'Noise: '. Say only what the examples show."
    ),
    "rulecand": (
        "Up to 80 of the developer's own messages that may state a standing rule, each {ref: "
        "[session_id, step], text, date}, not yet judged. Dataset history is refused; history "
        "the developer barred from this session is left out (see not_shown). Merge messages "
        "that say the same thing in different words, drop questions and one-off requests, then "
        "call symbiont_save_rules. Pass running_in if asked."
    ),
    "saverule": (
        "Save: [{rule (one line, at most 120 characters, an instruction in plain words), scope: "
        "repo|area, area? (a path, when scope is area), refs: [[session_id, step]] of the "
        "candidates it merges, dropped: [[session_id, step]] of candidates that are not "
        "rules}]. Repeat while remaining is above zero."
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
        _HARNESS,
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
        "symbiont_session_candidates", "summaries/candidates", _DESCRIPTIONS["sess"], _HARNESS, []
    ),
    _tool(
        "symbiont_save_session_summaries",
        "summaries/save",
        _DESCRIPTIONS["savesum"],
        {"summaries": _ITEMS},
        ["summaries"],
    ),
    _tool("symbiont_topic_candidates", "topics/candidates", _DESCRIPTIONS["topcand"], _HARNESS, []),
    _tool(
        "symbiont_save_topics",
        "topics/save",
        _DESCRIPTIONS["savetop"],
        {"topics": _ITEMS, "frictions": _ITEMS, "correction_groups": _ITEMS} | _HARNESS,
        ["topics"],
    ),
    _tool(
        "symbiont_group_candidates", "verdicts/candidates", _DESCRIPTIONS["groupcand"], _HARNESS, []
    ),
    _tool(
        "symbiont_save_group_verdicts",
        "verdicts/save",
        _DESCRIPTIONS["savegroup"],
        {"verdicts": _ITEMS},
        ["verdicts"],
    ),
    _tool("symbiont_rule_candidates", "rules/candidates", _DESCRIPTIONS["rulecand"], _HARNESS, []),
    _tool(
        "symbiont_save_rules",
        "rules/save",
        _DESCRIPTIONS["saverule"],
        {"rules": _ITEMS} | _HARNESS,
        ["rules"],
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
    name: str,
    arguments: dict[str, Any],
    environ: Mapping[str, str],
    known: Sequence[Harness] = HARNESSES,
) -> tuple[str, dict[str, Any]]:
    """The service route and request body for a tool call; the harness is read from the host."""
    body = dict(arguments)
    if name in _READS_HISTORY:
        body["running_in"] = _running_in(arguments, environ, known)
    return BY_NAME[name]["route"], body


def _running_in(
    arguments: dict[str, Any], environ: Mapping[str, str], known: Sequence[Harness]
) -> str:
    """The host says so in its environment; otherwise the model must say which harness it is."""
    found = detect(environ, known)
    if found is not None:
        return found.id
    ids = [entry.id for entry in known]
    chosen = arguments.get("running_in")
    if chosen not in ids:
        raise ValueError(f"pass running_in: {' or '.join(ids)}")
    return str(chosen)


def as_text(reply: dict[str, Any]) -> str:
    """The service's reply as text for the model."""
    return json.dumps(reply, indent=1)
