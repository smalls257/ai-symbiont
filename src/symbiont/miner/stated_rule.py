"""A standing rule the developer's session model confirmed from what the developer said.

The rule reaches the dashboard as the developer's own instruction, so a paragraph, a
credential or a ref the model invented would read as the developer's word. Every item is
checked and a bad one raises `StatedRuleError` naming the field. Pure.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from symbiont.miner.secrets import scrub

# One line of a dashboard row; a longer rule is a paragraph, not an instruction.
MAX_RULE_CHARS = 120
MAX_AREA_CHARS = 120

Ref = tuple[str, int]


class StatedRuleError(ValueError):
    """A rule or ref that does not have the shape the route takes; the message names the field."""


class RuleScope(StrEnum):
    """Whether the rule holds in the whole repository or only under one path."""

    REPO = "repo"
    AREA = "area"


@dataclass(frozen=True)
class StatedRule:
    """One confirmed rule: its words, its scope, and the candidates it merges."""

    rule: str
    scope: RuleScope
    area: str
    refs: tuple[Ref, ...]

    @property
    def key(self) -> str:
        """`rule:` plus the smallest ref, so the key survives a rewording of the same rule."""
        session_id, step = min(self.refs)
        return f"rule:{session_id}:{step}"


def ref_from(value: Any, field: str) -> Ref:
    """A checked (session id, step) from a two-element list; raises StatedRuleError."""
    ok = isinstance(value, (list, tuple)) and len(value) == 2
    if not ok or not isinstance(value[0], str) or not value[0]:
        raise StatedRuleError(f"{field} must be [session_id, step] pairs from the candidates")
    if not isinstance(value[1], int) or isinstance(value[1], bool):
        raise StatedRuleError(f"{field} must be [session_id, step] pairs from the candidates")
    return value[0], value[1]


def refs_from(value: Any, field: str) -> tuple[Ref, ...]:
    """Checked refs from a list; raises StatedRuleError."""
    if not isinstance(value, list):
        raise StatedRuleError(f"{field} must be a list of [session_id, step] pairs")
    return tuple(ref_from(item, field) for item in value)


def stated_rule_from(item: Mapping[str, Any]) -> tuple[StatedRule, tuple[Ref, ...]]:
    """A checked rule and the refs it marks as not rules; raises StatedRuleError."""
    text = _one_line(item.get("rule"))
    scope = _scope(item.get("scope"))
    area = _area(scope, item.get("area"))
    refs = refs_from(item.get("refs"), "refs")
    if not refs:
        raise StatedRuleError(f"rule {text!r} needs at least one ref from the candidates")
    dropped = refs_from(item.get("dropped", []), "dropped")
    return StatedRule(text, scope, area, refs), dropped


def _one_line(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StatedRuleError("rule must be text")
    text = scrub(value.strip())
    if len(text.splitlines()) != 1:
        raise StatedRuleError(f"rule {text[:40]!r} must be one line")
    if len(text) > MAX_RULE_CHARS:
        raise StatedRuleError(f"rule {text[:40]!r} is over {MAX_RULE_CHARS} characters")
    return text


def _scope(value: Any) -> RuleScope:
    try:
        return RuleScope(value)
    except ValueError:
        raise StatedRuleError("scope must be repo or area") from None


def _area(scope: RuleScope, value: Any) -> str:
    if scope is RuleScope.REPO:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_AREA_CHARS:
        raise StatedRuleError(f"area must be a path of at most {MAX_AREA_CHARS} characters")
    return scrub(value.strip())
