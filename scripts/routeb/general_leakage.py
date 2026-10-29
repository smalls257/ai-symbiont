"""Scan every general text against every evaluation task: gold lines, specific names, closeness.

A gold line or a code name used by an evaluation fix but rare in other fixes stops the build; a
lesson that teaches the kind of place an evaluation fix lands in is reported as pattern-close,
since general repo knowledge is meant to apply there. Pure.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from general_lesson import GeneralLesson
from general_places import task_place_kinds
from sqlglot_leakage import LeakageError, gold_lines, leaks_by_task
from sqlglot_places import Place, changed_lines

CONVENTION_PATCHES = 5  # a name in this many non-evaluation fixes is a convention, not one fix
NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")


def code_shaped(name: str) -> bool:
    """`TokenType`, `_parse_x`, `SERIAL`: an underscore, an inner capital or all capitals."""
    return "_" in name or name.isupper() or any(ch.isupper() for ch in name[1:])


def patch_names(patch: str) -> set[str]:
    """Code-shaped names on a patch's changed lines."""
    return {
        name for line in changed_lines(patch) for name in NAME.findall(line) if code_shaped(name)
    }


def conventions(source_patches: Iterable[str]) -> set[str]:
    """Names on the changed lines of at least CONVENTION_PATCHES non-evaluation fixes."""
    seen: Counter[str] = Counter(name for patch in source_patches for name in patch_names(patch))
    return {name for name, count in seen.items() if count >= CONVENTION_PATCHES}


def specific_names(eval_patches: Mapping[str, str], common: set[str]) -> dict[str, set[str]]:
    """Per evaluation task, the code names of its fix that are not conventions."""
    return {task: patch_names(patch) - common for task, patch in eval_patches.items()}


def name_hits(text: str, names: Mapping[str, set[str]]) -> dict[str, list[str]]:
    """Evaluation task to its specific names found as whole words in `text`."""
    words = set(NAME.findall(text))
    found = {task: sorted(words & own) for task, own in names.items()}
    return {task: hit for task, hit in found.items() if hit}


def leaking_keys(
    texts: Mapping[str, str], eval_patches: Mapping[str, str], common: set[str]
) -> set[str]:
    """Keys of the texts that would fail `scan`."""
    gold = {task: gold_lines(patch) for task, patch in eval_patches.items()}
    names = specific_names(eval_patches, common)
    return {
        key for key, text in texts.items() if leaks_by_task(text, gold) or name_hits(text, names)
    }


def scan(texts: Mapping[str, str], eval_patches: Mapping[str, str], common: set[str]) -> dict:
    """Check every text; raise LeakageError naming each hit, else return the scan counts."""
    gold = {task: gold_lines(patch) for task, patch in eval_patches.items()}
    names = specific_names(eval_patches, common)
    hits = {}
    for key, text in texts.items():
        found = leaks_by_task(text, gold) | {
            f"{t} (name)": n for t, n in name_hits(text, names).items()
        }
        if found:
            hits[key] = found
    if hits:
        raise LeakageError(f"{len(hits)} texts leak evaluation fixes: {hits}")
    return {
        "texts_checked": len(texts),
        "eval_tasks": len(gold),
        "gold_lines_checked": sum(len(lines) for lines in gold.values()),
        "specific_names_checked": sum(len(n) for n in names.values()),
        "hits": 0,
    }


def pattern_close(lessons: Sequence[GeneralLesson], places: Mapping[str, Sequence[Place]]) -> dict:
    """Per evaluation task, the lessons that teach a kind of place its fix lands in."""
    found = {}
    for task, task_places in places.items():
        kinds = {str(kind) for kind in task_place_kinds(task_places)}
        found[task] = sorted(lesson.lesson_id for lesson in lessons if kinds & set(lesson.teaches))
    return found
