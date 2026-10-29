"""Implementation lessons: how new capability is added to sqlglot, from non-evaluation features.

Counts come from the upstream feature patches (kind rule in general_kinds.py): where they add
code, whether new map entries reuse an existing helper, and how their tests are written. Pure.
"""

import re
from collections.abc import Sequence

from general_evidence import SourceTask
from general_lesson import GeneralLesson, LessonKind, share
from general_places import PlaceKind as K
from general_places import task_place_kinds

TEST = "python -m unittest tests.dialects.test_<dialect>"
EXPRESSIONS_DIFF = "diff --git a/sqlglot/expressions.py"


def adds_expression_class(task: SourceTask) -> bool:
    """The patch adds a class to sqlglot/expressions.py."""
    if EXPRESSIONS_DIFF not in task.gold_patch:
        return False
    section = task.gold_patch.split(EXPRESSIONS_DIFF, 1)[1].split("diff --git", 1)[0]
    return any(re.match(r"\+class \w+\(", line) for line in section.splitlines())


def _ids(tasks: Sequence[SourceTask]) -> tuple[str, ...]:
    return tuple(sorted(task.task for task in tasks))


def new_function(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """A SQL function a dialect lacks: entries, and a class only when none exists."""
    classes = [task for task in tasks if adds_expression_class(task)]
    maps = [
        t
        for t in tasks
        if task_place_kinds(t.places) & {K.DIALECT_PARSER_MAP, K.DIALECT_TRANSFORMS}
    ]
    return GeneralLesson(
        lesson_id="impl-new-function",
        kind=LessonKind.IMPLEMENTATION,
        situation="The issue asks for a function or type a dialect does not support yet.",
        happened=(
            f"{share(len(maps), len(tasks))} upstream feature patches added a dialect "
            f"`Parser.FUNCTIONS` or `Generator.TRANSFORMS` entry; only {len(classes)} added a "
            "class to `sqlglot/expressions.py`."
        ),
        resolved=(
            "First grep `sqlglot/expressions.py` for an existing class that means the same thing; "
            "if one exists, map the dialect's name to it in both directions; add a `Func` subclass "
            "with `arg_types` only when none does."
        ),
        check=f"`grep -n 'class <Name>' sqlglot/expressions.py`, then `{TEST}`.",
        support={"tasks": len(maps), "class_tasks": len(classes), "of_tasks": len(tasks)},
        source_tasks=_ids(maps),
        teaches=(str(K.DIALECT_PARSER_MAP), str(K.DIALECT_TRANSFORMS), str(K.EXPRESSIONS)),
    )


def mirror_neighbor(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """Copy the shape of the closest existing entry."""
    reused = sum(task.entry_reuse[0] for task in tasks)
    calling = sum(task.entry_reuse[1] for task in tasks)
    hit = [task for task in tasks if task.entry_reuse[1]]
    return GeneralLesson(
        lesson_id="impl-mirror-neighbor",
        kind=LessonKind.IMPLEMENTATION,
        situation="You are about to write a new map entry or method for a dialect.",
        happened=(
            f"In upstream feature patches, {share(reused, calling)} new map entries that call a "
            "helper reuse one the same file already used (`rename_func`, a `_build_*` or `*_sql` "
            "helper)."
        ),
        resolved="They copied the closest existing entry in the same map and changed the names.",
        check=(
            "grep the map for an entry with the same argument shape and copy it; write a new "
            "helper only if none fits."
        ),
        support={"entries_reused": reused, "entries_calling": calling, "tasks": len(hit)},
        source_tasks=_ids(hit),
    )


def new_syntax(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """New keywords and clauses span the tokenizer, parser, expression and generator."""
    multi = [task for task in tasks if len(task.gold_files) > 1]
    tokens = [t for t in tasks if task_place_kinds(t.places) & {K.DIALECT_TOKENIZER, K.TOKENS}]
    return GeneralLesson(
        lesson_id="impl-new-syntax",
        kind=LessonKind.IMPLEMENTATION,
        situation="The issue asks for a new keyword, clause or statement form.",
        happened=(
            f"{share(len(multi), len(tasks))} upstream feature patches changed two or more source "
            f"files; {len(tokens)} added a keyword in a `Tokenizer.KEYWORDS` map or a `TokenType`."
        ),
        resolved=(
            "The usual chain is: token (`TokenType` and the dialect's `Tokenizer.KEYWORDS`), a "
            "`_parse_<thing>` that builds the new node; an `arg_types` key for the new part; and "
            "a generator `<name>_sql` that prints it."
        ),
        check=(
            f"edit the chain in that order, re-running `{TEST}` after the parser step and the "
            "generator step."
        ),
        support={"tasks": len(multi), "token_tasks": len(tokens), "of_tasks": len(tasks)},
        source_tasks=_ids(multi),
        teaches=(
            str(K.TOKENS),
            str(K.DIALECT_TOKENIZER),
            str(K.SHARED_PARSER),
            str(K.SHARED_GENERATOR),
        ),
    )


def test_next_to_neighbors(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """Feature tests go beside the existing ones."""
    validates = [
        t for t in tasks if "validate_identity" in t.test_patch or "validate_all" in t.test_patch
    ]
    return GeneralLesson(
        lesson_id="impl-test-next-to-neighbors",
        kind=LessonKind.IMPLEMENTATION,
        situation="Your new support works on one example and you want to prove it.",
        happened=(
            f"{share(len(validates), len(tasks))} upstream feature patches added "
            "`validate_identity` or `validate_all` lines beside similar ones in the dialect's "
            "test file."
        ),
        resolved=(
            "A round trip through the dialect (read it, write it back) is the check the "
            "maintainers use."
        ),
        check=(
            "`python -c \"import sqlglot; print(sqlglot.transpile(SQL, read='<d>', "
            "write='<d>'))\"` "
            f"must print SQL unchanged; then `{TEST}`."
        ),
        support={"tasks": len(validates), "of_tasks": len(tasks)},
        source_tasks=_ids(validates),
    )


def implementation_lessons(features: Sequence[SourceTask]) -> list[GeneralLesson]:
    """Every implementation lesson over the non-evaluation feature tasks."""
    builders = (new_function, mirror_neighbor, new_syntax, test_next_to_neighbors)
    return [builder(features) for builder in builders]
