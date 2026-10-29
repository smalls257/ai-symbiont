"""The review-flag label on one PR: which hunks a reviewer flagged, and which changed later.

Definition: docs/research/2026-10-28-aidev-review-flag.md, section 2. A unit is one added hunk,
followed through later commits in `pr_commits` row order (checked by `order.py`). A unit whose
fate cannot be seen is `unknown` and one with no later commit is `censored`; neither is ever
`survived`. Pure: ordered commits and comments in, labels out.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from hunks import FileChange, Hunk, Interval


class Outcome(StrEnum):
    """What became of a unit after the point it is judged from."""

    CHANGED = "changed"
    SURVIVED = "survived"
    CENSORED = "censored"  # no commit after that point
    UNKNOWN = "unknown"  # a later commit's change to the file cannot be read


class Flag(StrEnum):
    """Who flagged a unit: a human reviewer, only a bot reviewer, or nobody."""

    HUMAN = "human"
    BOT = "bot"
    NONE = "none"


@dataclass(frozen=True)
class FileState:
    """One file in one commit; `hunks` is None when the patch is missing or unreadable."""

    status: str
    hunks: tuple[Hunk, ...] | None


@dataclass(frozen=True)
class Commit:
    """One commit of a PR; `files` is None when the dataset has no file rows for it."""

    sha: str
    files: dict[str, FileState] | None


@dataclass(frozen=True)
class Comment:
    """A thread-opening inline review comment, reduced to where it points."""

    comment_id: int
    sha: str  # original_commit_id: the commit the reviewer saw
    path: str
    line: int | None  # anchor_line of its diff_hunk; None on the old side
    human: bool


@dataclass
class Unit:
    """One added hunk and what became of it."""

    commit_index: int
    path: str
    hunk: Hunk
    lines: list[Interval]
    changed_at: int | None = None
    unknown_at: int | None = None
    human_at: int | None = None  # first commit a human comment flagged it at
    bot_at: int | None = None
    comment_ids: list[int] = field(default_factory=list)

    def live(self) -> bool:
        """Still followed: neither changed nor lost from view."""
        return self.changed_at is None and self.unknown_at is None

    def flag(self) -> Flag:
        """The strongest flag on this unit."""
        if self.human_at is not None:
            return Flag.HUMAN
        return Flag.BOT if self.bot_at is not None else Flag.NONE

    def outcome_after(self, point: int, last_index: int) -> Outcome:
        """The unit's fate counting only commits after `point`."""
        if self.changed_at is not None and self.changed_at > point:
            return Outcome.CHANGED
        if self.unknown_at is not None:
            return Outcome.UNKNOWN
        return Outcome.CENSORED if point >= last_index else Outcome.SURVIVED


@dataclass(frozen=True)
class PrLabels:
    """Every unit of a PR and why each comment did or did not anchor."""

    units: tuple[Unit, ...]
    anchoring: Counter[str]
    last_index: int
    first_review: int | None  # commit index of the earliest anchorable human comment


def label_pr(commits: Sequence[Commit], comments: Sequence[Comment]) -> PrLabels:
    """Label every unit of one PR; comments on commits outside the PR are counted, not used."""
    index_of = {commit.sha: i for i, commit in enumerate(commits)}
    anchoring: Counter[str] = Counter()
    at_commit: dict[int, list[Comment]] = {}
    for comment in comments:
        if comment.sha not in index_of:
            anchoring["commit_not_in_pr"] += 1
        elif comment.line is None:
            anchoring["old_side"] += 1
        else:
            at_commit.setdefault(index_of[comment.sha], []).append(comment)
    units: list[Unit] = []
    for position, commit in enumerate(commits):
        _advance(units, commit, position)
        units.extend(_new_units(commit, position))
        for comment in at_commit.get(position, []):
            anchoring[_attribute(units, comment, position)] += 1
    human = [index_of[c.sha] for c in comments if c.human and c.sha in index_of]
    return PrLabels(tuple(units), anchoring, len(commits) - 1, min(human, default=None))


def _advance(units: list[Unit], commit: Commit, position: int) -> None:
    for unit in units:
        if not unit.live():
            continue
        if commit.files is None:
            unit.unknown_at = position
            continue
        state = commit.files.get(unit.path)
        if state is not None:
            _apply(unit, state, position)


def _apply(unit: Unit, state: FileState, position: int) -> None:
    if state.status == "removed":
        unit.changed_at = position
        return
    if state.hunks is None:
        unit.unknown_at = position
        return
    change = FileChange.of(list(state.hunks))
    if any(change.touches(span) for span in unit.lines):
        unit.changed_at = position
        return
    unit.lines = [change.shift(span) for span in unit.lines]


def _new_units(commit: Commit, position: int) -> list[Unit]:
    if commit.files is None:
        return []
    return [
        Unit(position, path, hunk, list(hunk.added_intervals()))
        for path, state in commit.files.items()
        for hunk in state.hunks or ()
        if hunk.added
    ]


def _attribute(units: list[Unit], comment: Comment, position: int) -> str:
    on_file = [u for u in units if u.path == comment.path]
    owner = next((u for u in on_file if u.live() and _holds(u.lines, comment.line)), None)
    if owner is None:
        lost = any(u.unknown_at is not None for u in on_file)
        return "file_untracked" if lost else "line_not_added_in_pr"
    _flag(owner, comment, position)
    return "anchored"


def _flag(owner: Unit, comment: Comment, position: int) -> None:
    owner.comment_ids.append(comment.comment_id)
    if comment.human and owner.human_at is None:
        owner.human_at = position
    if not comment.human and owner.bot_at is None:
        owner.bot_at = position


def _holds(lines: list[Interval], line: int | None) -> bool:
    return line is not None and any(first <= line <= last for first, last in lines)
