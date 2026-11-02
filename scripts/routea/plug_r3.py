"""Plug round 3's items and choices (prereg/2026-10-29-plug-judge.md): the split checks, the seen
set under a wording never trained on, the thresholded ranker, threshold fits and per-repo rates.

Every check that can fail does: a repo or lesson id shared by two splits, a habit repo inside a
split, or a meta-train list other than the prereg's raises; a fit with no safe point returns None.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import replace

from lessons import Lesson
from plug import SharedSplitError, lesson_key
from plug_judge import Choice, outcome_rates
from plug_r2_rows import phrase
from plug_situation import Item, lexical_rank, lexical_scores

PREREG_NAME = "2026-10-29-plug-judge.md"
RANKER_GRID = tuple(step / 4 for step in range(121))  # top IDF score 0 to 30 in steps of 0.25
SAFE_SILENCE, SAFE_WRONG = 0.80, 0.05
# sha256 of the 60 meta-train repo names, sorted, newline-joined (the prereg's split section).
META_REPOS_SHA256 = "cdf6df15b59e6ff5a3da9d64290a02b40d80202b44b17dfaedeb0270a47ff68e"
# H4's seen set: meta-train lessons under this wording, which no training row uses.
SEEN_WORDING = "Something broke. Repo: {repo}. Edited: {file}. Ran: `{failed}`. Saw: {error}"

Splits = dict[str, dict[str, list[Lesson]]]


class MetaListMismatchError(ValueError):
    """The meta-train repos differ from the prereg's list."""


def round3_splits(by_repo: dict[str, list[Lesson]], plan: dict) -> Splits:
    """Meta-train (every repo neither scored nor validation), validation and scored lessons."""
    held = set(plan["scored"]) | set(plan["validation"])
    return {
        "meta": {repo: by_repo[repo] for repo in sorted(by_repo) if repo not in held},
        "validation": {repo: by_repo[repo] for repo in sorted(plan["validation"])},
        "scored": {repo: by_repo[repo] for repo in sorted(plan["scored"])},
    }


def check_meta(splits: Splits) -> None:
    """Raise MetaListMismatchError unless the meta-train repos are the prereg's 60."""
    found = hashlib.sha256("\n".join(sorted(splits["meta"])).encode()).hexdigest()
    if found != META_REPOS_SHA256:
        raise MetaListMismatchError(f"meta-train repos hash {found[:12]}, the prereg pins another")


def lesson_ids(split: dict[str, list[Lesson]]) -> set[str]:
    """Every lesson id in one split."""
    return {lesson.lesson_id for lessons in split.values() for lesson in lessons}


def refuse_overlap(splits: Splits, left: str, right: str) -> None:
    """Raise SharedSplitError if two splits share a repo or a lesson id."""
    shared = sorted(set(splits[left]) & set(splits[right])) or sorted(
        lesson_ids(splits[left]) & lesson_ids(splits[right])
    )
    if shared:
        raise SharedSplitError(f"{left} and {right} share {shared[:3]}")


def check_splits(splits: Splits, habit_repos: Sequence[str]) -> dict[str, int]:
    """Raise on any repo or lesson id shared by two splits, or a habit repo in any split; return
    each non-meta split's count of lessons whose failure key also occurs in meta-train."""
    names = sorted(splits)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            refuse_overlap(splits, left, right)
        if set(habit_repos) & set(splits[left]):
            raise SharedSplitError(f"habit repos inside {left}")
    keys = meta_keys(splits)
    return {
        name: sum(
            lesson_key(lesson) in keys for lessons in splits[name].values() for lesson in lessons
        )
        for name in names
        if name != "meta"
    }


def meta_keys(splits: Splits) -> set:
    """The failure keys of every meta-train lesson."""
    return {lesson_key(lesson) for lessons in splits["meta"].values() for lesson in lessons}


def source_of(lessons: Sequence[Lesson]) -> Callable[[Item], Lesson]:
    """The lesson an item was built from (pick and silence items share it), by item id."""
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    return lambda item: by_id[item.item_id.rsplit("-", 1)[0]]


def reworded(items: Sequence[Item], lessons: Sequence[Lesson], wording: str) -> list[Item]:
    """The items with their situation rewritten from the source lesson's fields in `wording`."""
    source = source_of(lessons)
    return [replace(item, situation=phrase(wording, source(item))) for item in items]


def ranker_choices(items: Sequence[Item], threshold: float) -> list[Choice]:
    """The ranker's top lesson where its top score reaches the threshold, else silence."""
    found = []
    for item in items:
        lesson_id = lexical_rank(item)[0].lesson_id
        top = lexical_scores(item)[lesson_id]
        found.append(Choice(item.item_id, lesson_id if top >= threshold else None, top))
    return found


def top_score_range(items: Sequence[Item]) -> list[float]:
    """The lowest and highest top IDF score over the items, to check the grid covers them."""
    tops = [max(lexical_scores(item).values()) for item in items]
    return [round(min(tops), 2), round(max(tops), 2)]


def safe(rates: dict[str, float]) -> bool:
    """The point limits a threshold must meet when it is fitted."""
    return rates["silence"] >= SAFE_SILENCE and rates["wrong_pick"] <= SAFE_WRONG


def fit_lowest(
    items: Sequence[Item], choose: Callable[[float], list[Choice]], grid: Sequence[float]
) -> float | None:
    """The lowest grid threshold whose choices are safe on these items, or None if none is."""
    for threshold in sorted(grid):
        if safe(outcome_rates(items, choose(threshold))):
            return threshold
    return None


def per_repo(items: Sequence[Item], choices: Sequence[Choice], repo_of: dict[str, str]) -> dict:
    """outcome_rates per repo plus how many items it answered (precision is undefined at none);
    raises if a repo lacks pick or silence items."""
    by_id = {choice.item_id: choice for choice in choices}
    repos: dict[str, list[Item]] = {}
    for item in items:
        repos.setdefault(repo_of[item.item_id], []).append(item)
    for repo, group in repos.items():
        if all(i.applies is None for i in group) or all(i.applies is not None for i in group):
            raise ValueError(f"{repo} needs pick and silence items")
    return {
        repo: outcome_rates(group, [by_id[i.item_id] for i in group])
        | {"answered": sum(by_id[i.item_id].lesson_id is not None for i in group)}
        for repo, group in sorted(repos.items())
    }


def subset_rates(items: Sequence[Item], choices: Sequence[Choice], keep: Callable) -> dict:
    """outcome_rates on the items whose source lesson passes `keep` (pick and silence together)."""
    kept = [item for item in items if keep(item)]
    by_id = {choice.item_id: choice for choice in choices}
    return {"items": len(kept), **outcome_rates(kept, [by_id[i.item_id] for i in kept])}


def wrong_from(items: Sequence[Item], choices: Sequence[Choice], ids: set[str]) -> dict:
    """How many wrong picks there are and the share that chose a lesson id in `ids`."""
    applies = {i.item_id: (i.applies.lesson_id if i.applies else None) for i in items}
    wrong = [c for c in choices if c.lesson_id is not None and c.lesson_id != applies[c.item_id]]
    hits = sum(c.lesson_id in ids for c in wrong)
    return {"wrong_picks": len(wrong), "share": round(hits / len(wrong), 4) if wrong else 0.0}
