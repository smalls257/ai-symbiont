"""Repo-knowledge and implementation lessons from the upstream fixes of non-evaluation tasks.

Each lesson names a kind of place (a dialect generator's TRANSFORMS map, the shared parser) and
how many upstream fixes landed there; it never names one dialect's entry or one task's fix. Pure.
"""

from collections.abc import Sequence

from general_evidence import SourceTask
from general_kinds import TaskKind
from general_lesson import GeneralLesson, LessonKind
from general_places import PlaceKind as K
from general_places import shared_only, task_place_kinds

TEST = "python -m unittest tests.dialects.test_<dialect>"


def _kinds(task: SourceTask) -> frozenset[K]:
    return task_place_kinds(task.places)


def _touching(tasks: Sequence[SourceTask], kinds: set[K]) -> list[SourceTask]:
    return [task for task in tasks if _kinds(task) & kinds]


def _ids(tasks: Sequence[SourceTask]) -> tuple[str, ...]:
    return tuple(sorted(task.task for task in tasks))


def _dialect_tested(task: SourceTask) -> bool:
    return bool(task.test_modules) and all(
        m.startswith("tests.dialects.") for m in task.test_modules
    )


def dialect_output(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """Wrong SQL text for one dialect: that dialect's Generator."""
    kinds = {K.DIALECT_TRANSFORMS, K.DIALECT_GENERATOR}
    hit = _touching(tasks, kinds)
    maps = _touching(tasks, {K.DIALECT_TRANSFORMS})
    return GeneralLesson(
        lesson_id="repo-dialect-output",
        kind=LessonKind.REPO,
        situation="One dialect writes the wrong SQL text for a construct that parses correctly.",
        happened=(
            "When one dialect writes the wrong SQL, the fix is usually in that dialect's "
            "`Generator`."
        ),
        resolved=(
            "Most often it is an entry of the nested `<Dialect>.Generator.TRANSFORMS` map in "
            "`sqlglot/dialects/<dialect>.py` (expression class to SQL); otherwise a `<name>_sql` "
            "method or `TYPE_MAPPING` on the same class."
        ),
        check=(
            "find the expression class with `repr(parse_one(SQL))`, grep its name in the dialect "
            f"file, then `{TEST}`."
        ),
        support={"tasks": len(hit), "transforms_tasks": len(maps), "of_tasks": len(tasks)},
        source_tasks=_ids(hit),
        teaches=tuple(str(kind) for kind in kinds),
    )


def dialect_parsing(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """A dialect reads SQL wrong: its Parser maps, methods and Tokenizer."""
    kinds = {K.DIALECT_PARSER_MAP, K.DIALECT_PARSER_METHOD, K.DIALECT_TOKENIZER}
    hit = _touching(tasks, kinds)
    tokens = _touching(tasks, {K.DIALECT_TOKENIZER, K.TOKENS})
    return GeneralLesson(
        lesson_id="repo-dialect-parsing",
        kind=LessonKind.REPO,
        situation=(
            "One dialect parses a function, keyword or clause into the wrong tree, or fails to "
            "parse it."
        ),
        happened=(
            "When one dialect reads SQL wrongly, the fix is usually in that dialect's `Parser` "
            "or `Tokenizer`."
        ),
        resolved=(
            "Function names map to builders in `<Dialect>.Parser.FUNCTIONS`; clauses are "
            "`_parse_<thing>` overrides on `<Dialect>.Parser`; keywords are "
            "`<Dialect>.Tokenizer.KEYWORDS` entries, sometimes with a new `TokenType` in "
            "`sqlglot/tokens.py`."
        ),
        check=(
            "compare `repr(parse_one(SQL, read='<dialect>'))` with the tree you expect, then "
            f"`{TEST}`."
        ),
        support={"tasks": len(hit), "token_tasks": len(tokens), "of_tasks": len(tasks)},
        source_tasks=_ids(hit),
        teaches=tuple(str(kind) for kind in kinds | {K.TOKENS}),
    )


def shared_layer(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """A dialect's failing test fixed outside the dialect file."""
    tested = [task for task in tasks if _dialect_tested(task)]
    shared = [task for task in tested if shared_only(_kinds(task))]
    return GeneralLesson(
        lesson_id="repo-shared-layer",
        kind=LessonKind.REPO,
        situation=(
            "The failing test is a dialect test but the dialect file has no code for the construct."
        ),
        happened=("A failing dialect test is often fixed without touching any dialect file."),
        resolved=(
            "Those fixes go in the shared `sqlglot/parser.py` (`Parser._parse_<thing>`), "
            "`sqlglot/generator.py` (`Generator.<name>_sql`) or `sqlglot/expressions.py` (an "
            "expression's `arg_types`)."
        ),
        check=(
            "grep the dialect file first; if nothing matches, grep `sqlglot/parser.py` and "
            "`sqlglot/generator.py`."
        ),
        support={"tasks": len(shared), "of_tasks": len(tested)},
        source_tasks=_ids(shared),
        teaches=(str(K.SHARED_PARSER), str(K.SHARED_GENERATOR), str(K.EXPRESSIONS)),
    )


def test_layout(tasks: Sequence[SourceTask]) -> GeneralLesson:
    """Where the tests are and how a fix is tested."""
    tested = [task for task in tasks if _dialect_tested(task)]
    validates = [
        t for t in tasks if "validate_identity" in t.test_patch or "validate_all" in t.test_patch
    ]
    new_files = [task for task in tasks if "--- /dev/null" in task.test_patch]
    return GeneralLesson(
        lesson_id="repo-test-layout",
        kind=LessonKind.REPO,
        situation="You need to know which test proves the fix.",
        happened=(
            "The failing tests are almost always in `tests/dialects/test_<dialect>.py`, plain "
            "unittest classes."
        ),
        resolved=(
            "Fixes add `self.validate_identity(sql)` or `self.validate_all(sql, read=..., "
            "write=...)` lines to an existing test file; they do not add test files."
        ),
        check=(
            f"`{TEST}` for the dialect named in the issue; `python -m unittest "
            "tests.test_transpile` for shared code."
        ),
        support={
            "tasks": len(tested),
            "validate_tasks": len(validates),
            "new_test_files": len(new_files),
        },
        source_tasks=_ids(tested),
    )


def knowledge_lessons(tasks: Sequence[SourceTask]) -> list[GeneralLesson]:
    """Repo-knowledge lessons over every non-evaluation task whose places resolved."""
    resolved = [task for task in tasks if task.places_resolved]
    return [
        builder(resolved)
        for builder in (dialect_output, dialect_parsing, shared_layer, test_layout)
    ]


def features(tasks: Sequence[SourceTask]) -> list[SourceTask]:
    """The feature tasks whose places resolved."""
    return [task for task in tasks if task.kind is TaskKind.FEATURE and task.places_resolved]
