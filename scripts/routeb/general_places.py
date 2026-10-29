"""Sort where an upstream sqlglot fix landed into a handful of kinds a lesson can name.

`Snowflake.Generator.TRANSFORMS` and `BigQuery.Generator.TRANSFORMS` are one kind of place,
"a dialect generator's TRANSFORMS map"; a lesson teaches the kind, never one dialect's entry. Pure.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from enum import StrEnum

from sqlglot_places import Place


class PlaceKind(StrEnum):
    """Kinds of place a sqlglot change lands in."""

    DIALECT_TRANSFORMS = "dialect Generator.TRANSFORMS map"
    DIALECT_GENERATOR = "dialect Generator method or type map"
    DIALECT_PARSER_MAP = "dialect Parser function map"
    DIALECT_PARSER_METHOD = "dialect Parser _parse_ method"
    DIALECT_TOKENIZER = "dialect Tokenizer keywords"
    DIALECT_SETTING = "dialect class setting"
    DIALECT_HELPER = "dialect module helper or import"
    SHARED_PARSER = "shared parser.py"
    SHARED_GENERATOR = "shared generator.py"
    EXPRESSIONS = "expressions.py"
    TOKENS = "tokens.py"
    OTHER_MODULE = "other module"


_SHARED = {
    "sqlglot/parser.py": PlaceKind.SHARED_PARSER,
    "sqlglot/generator.py": PlaceKind.SHARED_GENERATOR,
    "sqlglot/expressions.py": PlaceKind.EXPRESSIONS,
    "sqlglot/tokens.py": PlaceKind.TOKENS,
}
_DIALECT = (
    (re.compile(r"\.Generator\.TRANSFORMS$"), PlaceKind.DIALECT_TRANSFORMS),
    (re.compile(r"\.Generator\b"), PlaceKind.DIALECT_GENERATOR),
    (re.compile(r"\.Parser\.[A-Z_]+$"), PlaceKind.DIALECT_PARSER_MAP),
    (re.compile(r"\.Parser\b"), PlaceKind.DIALECT_PARSER_METHOD),
    (re.compile(r"\.Tokenizer\b"), PlaceKind.DIALECT_TOKENIZER),
    (re.compile(r"^[A-Z]\w*(\.[A-Z_]+)?$"), PlaceKind.DIALECT_SETTING),
)


def place_kind(place: Place) -> PlaceKind:
    """The kind of one place."""
    if place.file in _SHARED:
        return _SHARED[place.file]
    if not place.file.startswith("sqlglot/dialects/"):
        return PlaceKind.OTHER_MODULE
    return next(
        (kind for sign, kind in _DIALECT if sign.search(place.name)), PlaceKind.DIALECT_HELPER
    )


def task_place_kinds(places: Iterable[Place]) -> frozenset[PlaceKind]:
    """The kinds one task's fix touched."""
    return frozenset(place_kind(place) for place in places)


def tasks_per_kind(per_task: Sequence[frozenset[PlaceKind]]) -> dict[str, int]:
    """How many tasks touched each kind of place."""
    found: Counter[str] = Counter(str(kind) for kinds in per_task for kind in kinds)
    return {str(kind): found[str(kind)] for kind in PlaceKind}


DIALECT_KINDS = frozenset(kind for kind in PlaceKind if kind.name.startswith("DIALECT_"))


def shared_only(kinds: frozenset[PlaceKind]) -> bool:
    """The fix touched no dialect file."""
    return bool(kinds) and not kinds & DIALECT_KINDS


ENTRY_VALUE = re.compile(r"""^\+\s*(?:["'][\w ]+["']|exp\.\w+|TokenType\.\w+)\s*:\s*(.+)$""")
CALLED = re.compile(r"\b([A-Za-z_]\w*)\(")


def entry_reuse(patch: str, sources: dict[str, str]) -> tuple[int, int]:
    """(added map entries that call a helper the file already had, added entries calling one)."""
    reused = total = 0
    path = None
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            path = line.split(" b/")[-1]
        found = ENTRY_VALUE.match(line) if path in sources else None
        called = (
            [name for name in CALLED.findall(found.group(1)) if name != "lambda"] if found else []
        )
        if not called:
            continue
        total += 1
        reused += any(re.search(rf"\b{re.escape(name)}\b", sources[path]) for name in called)
    return reused, total
