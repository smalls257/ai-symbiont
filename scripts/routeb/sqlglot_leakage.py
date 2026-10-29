"""Refuse any training text that carries a line of an evaluation task's gold patch.

An adapter trained on the answer's own code would turn "the lesson helped" into "the answer was in
the weights", and nothing afterwards could tell the two apart. So every row is checked against every
evaluation task's gold diff and a hit raises: a leaking lesson is rewritten by hand, never dropped
quietly. A lesson may name where a fix goes (`Redshift.Generator.TRANSFORMS`), not paste its line.
"""

import re
from collections.abc import Iterable, Mapping

from sqlglot_places import changed_lines

# Shorter gold lines are syntax glue (`)`, `},`, `else:`) that any prose about code contains.
MIN_LINE_CHARS = 10
# A backticked span with assignment, call or literal syntax is code, not a name: `x = True` is a
# pasted fix, `Parser._parse_types` is a place.
CODE_SYNTAX = re.compile(r"[=(\[{:\"']")
SPAN = re.compile(r"`([^`]+)`")


class LeakageError(ValueError):
    """A training text contains a gold-patch line of an evaluation task."""


def _flat(text: str) -> str:
    return " ".join(text.split())


def gold_lines(patch: str) -> set[str]:
    """The gold patch's added and removed lines, whitespace-collapsed, long enough to be code."""
    found = {_flat(line) for line in changed_lines(patch)}
    return {line for line in found if len(line) >= MIN_LINE_CHARS and re.search(r"\w{3}", line)}


def leaked(text: str, lines: Iterable[str]) -> list[str]:
    """Gold lines found in `text`: whole lines, or a backticked code span cut from one."""
    flat = _flat(text)
    spans = [
        _flat(span)
        for span in SPAN.findall(text)
        if len(_flat(span)) >= MIN_LINE_CHARS and CODE_SYNTAX.search(span)
    ]
    return sorted({line for line in lines if line in flat or any(span in line for span in spans)})


def leaks_by_task(text: str, gold: Mapping[str, set[str]]) -> dict[str, list[str]]:
    """Evaluation task id to the gold lines of that task found in `text`."""
    found = {task: leaked(text, lines) for task, lines in gold.items()}
    return {task: lines for task, lines in found.items() if lines}


def refuse_leaks(texts: Mapping[str, str], gold: Mapping[str, set[str]]) -> int:
    """Check every text (id to text); raise LeakageError naming each hit, else return the count."""
    hits = {key: leaks_by_task(text, gold) for key, text in texts.items()}
    hits = {key: found for key, found in hits.items() if found}
    if hits:
        named = "; ".join(f"{key} carries gold of {sorted(found)}" for key, found in hits.items())
        raise LeakageError(f"{len(hits)} training texts leak: {named}")
    return len(texts)
