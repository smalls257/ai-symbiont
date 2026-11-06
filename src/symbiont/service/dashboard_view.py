"""The dashboard's one data object, built from a repository's lessons (schema 1).

Pain points are lessons grouped by kind of trouble; the turns and minutes per occurrence are
estimates from the length of the recorded fix, and the replay is an estimate, not a measurement.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from symbiont.core.failure_signature import failure_detail
from symbiont.core.notes import happened, render_lesson, resolution_clause
from symbiont.core.rule_relevance import situation_terms
from symbiont.miner.churn import FileChurn
from symbiont.miner.lesson_context import AuthoredLesson, LessonContext, Review, Verdict
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.screen import HoldReason
from symbiont.miner.secrets import scrub
from symbiont.miner.trained import lesson_id
from symbiont.service.candidate_summary import rule_summary
from symbiont.store.held_back import StruggleGroup

REPLAY_DAYS = 30
STRUGGLE_SHOWN = 20
CHURN_SHOWN = 20
MINUTES_PER_TURN = 0.7
KIND_OF_SIGNAL = {
    Signal.FAILED_COMMAND: "repeat",
    Signal.BLAST_RADIUS: "repeat",
    Signal.REWORKED_EDIT: "rework",
    Signal.REVIEW_FLAG: "rework",
    Signal.CORRECTION: "correction",
    Signal.LOOP: "loop",
}


@dataclass(frozen=True)
class RepoView:
    """Everything the dashboard shows about one repository."""

    project: str
    lessons: Sequence[Lesson]
    contexts: Mapping[str, LessonContext]
    session_dates: Mapping[str, date]
    reviews: Mapping[str, Review] = field(default_factory=dict)
    written: Sequence[AuthoredLesson] = ()
    focus: frozenset[str] = frozenset()
    # Lesson ids the developer annotated (words, priority or an explicit intentional choice).
    annotated: frozenset[str] = frozenset()
    # The nightly state (`never`, `trained` or `stale` with its sentence), or None when unknown.
    nightly: Mapping[str, object] | None = None
    # What the last mining counted instead of teaching: groups held back per reason, failures
    # that never showed a fix, and edits per file (churn).
    held_back: Mapping[HoldReason, int] = field(default_factory=dict)
    struggle: Sequence[StruggleGroup] = ()
    churn: Sequence[FileChurn] = ()


def dashboard_snapshot(view: RepoView, today: date) -> dict[str, Any]:
    """The object the dashboard page reads; session ids missing from the dates use today."""
    project, lessons = view.project, view.lessons
    order = _session_order(lessons, view.session_dates, today)
    if not order and view.written:
        order = {"written": (0, today)}
    groups = _grouped(lessons, view.reviews, view.focus)
    points = [_pain_point(n, group, order, view) for n, group in enumerate(groups, 1)]
    points += [
        _written_point(len(points) + n, item, order, view.contexts.get(item.ident))
        for n, item in enumerate(view.written, 1)
    ]
    first = min((item[1] for item in order.values()), default=today)
    days = {index: (when - first).days for index, when in order.values()}
    return {
        "schema": 1,
        "repo": {
            "name": project,
            "language": "",
            "today": today.isoformat(),
            "sessionsRead": len(order),
            "demo": False,
        },
        "sessions": [
            {"index": index, "day": days[index], "date": when.isoformat()}
            for index, when in sorted(order.values())
        ],
        "painPoints": [point for point, _ in points],
        "lessons": [lesson for _, lesson in points],
        "replay": _replay([p for p, _ in points], days, (today - first).days),
        "nightly": dict(view.nightly) if view.nightly is not None else None,
        **_counted_not_taught(view),
    }


def _counted_not_taught(view: RepoView) -> dict[str, Any]:
    """What mining held back, the failures with no shown fix, and where files churned."""
    return {
        "heldBack": {reason.value: count for reason, count in view.held_back.items()},
        "struggle": [_struggle_entry(group) for group in view.struggle[:STRUGGLE_SHOWN]],
        "churn": _churn_entries(view.churn),
    }


def _struggle_entry(group: StruggleGroup) -> dict[str, Any]:
    """A failure that never showed a fix: counted with its cost, never turned into a note."""
    return {
        "what": happened(group.signature),
        "sessions": group.sessions,
        "occurrences": group.occurrences,
        # One turn per failure is the least it cost: an estimate, not a measurement.
        "minutes": round(group.occurrences * MINUTES_PER_TURN, 1),
    }


def _churn_entries(churn: Sequence[FileChurn]) -> list[dict[str, Any]]:
    """The files edited most across sessions: where agents struggle with the code itself."""
    edits: dict[str, int] = defaultdict(int)
    sessions: dict[str, int] = defaultdict(int)
    for row in churn:
        edits[row.file] += row.edits
        sessions[row.file] += 1
    ranked = sorted(edits, key=lambda file: (-edits[file], file))[:CHURN_SHOWN]
    return [{"file": f, "edits": edits[f], "sessions": sessions[f]} for f in ranked]


TITLE_CHARS = 90


def _session_order(
    lessons: Sequence[Lesson], dates: Mapping[str, date], today: date
) -> dict[str, tuple[int, date]]:
    """Session id -> (index, date), oldest first."""
    ids = list(dict.fromkeys(lesson.pain_point.session_id for lesson in lessons))
    ranked = sorted(ids, key=lambda sid: (dates.get(sid, today), ids.index(sid)))
    return {sid: (index, dates.get(sid, today)) for index, sid in enumerate(ranked)}


def _grouped(
    lessons: Sequence[Lesson], reviews: Mapping[str, Review], focus: frozenset[str]
) -> list[list[Lesson]]:
    """Lessons grouped by kind of trouble (and by the reviewer's merges), focus matches first."""
    grouped: dict[Signature, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        grouped[lesson.pain_point.signature].append(lesson)
    groups = list(grouped.values())
    for group in list(groups):
        home = _merge_home(group, groups, reviews)
        if home is not None:
            home.extend(group)
            groups.remove(group)
    return sorted(
        groups,
        key=lambda group: -len(focus & situation_terms(happened(group[-1].pain_point.signature))),
    )


def row_of(lessons: Sequence[Lesson], reviews: Mapping[str, Review], ident: str) -> list[Lesson]:
    """The lessons the dashboard shows as one row with lesson `ident`; empty when none has it."""
    for group in _grouped(lessons, reviews, frozenset()):
        if ident in {lesson_id(item) for item in group}:
            return group
    return []


def row_title(group: Sequence[Lesson], reviews: Mapping[str, Review]) -> str:
    """The title the dashboard shows for a row: a reviewer's title, else what happened."""
    review = next(
        (reviews[lesson_id(item)] for item in reversed(group) if lesson_id(item) in reviews), None
    )
    title = review.title if review and review.title else happened(group[-1].pain_point.signature)
    return title[:TITLE_CHARS]


def _merge_home(
    group: list[Lesson], groups: list[list[Lesson]], reviews: Mapping[str, Review]
) -> list[Lesson] | None:
    """The group the reviewer asked this one to be merged into, if any."""
    wanted = {
        review.merge_with
        for item in group
        if (review := reviews.get(lesson_id(item))) and review.merge_with
    }
    for other in groups:
        if other is not group and wanted & {lesson_id(mate) for mate in other}:
            return other
    return None


def _pain_point(
    number: int,
    group: list[Lesson],
    order: Mapping[str, tuple[int, date]],
    view: RepoView,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One pain point and its lesson, for a group of lessons about the same trouble."""
    reviews, contexts = view.reviews, view.contexts
    review = next(
        (reviews[lesson_id(item)] for item in reversed(group) if lesson_id(item) in reviews), None
    )
    latest = group[-1]
    words = next(
        (contexts[lesson_id(item)] for item in reversed(group) if lesson_id(item) in contexts), None
    )
    sessions = sorted(order[item.pain_point.session_id][0] for item in group)
    return _point(number, latest, sessions, review), _lesson(
        number, latest, words, review, view.annotated
    )


def _point(
    number: int, latest: Lesson, sessions: list[int], review: Review | None
) -> dict[str, Any]:
    """The pain point's fields."""
    signature = latest.pain_point.signature
    turns = 1 + len(latest.resolution)
    title = review.title if review and review.title else happened(signature)
    return {
        "id": number,
        "kind": KIND_OF_SIGNAL[signature.signal],
        "title": title[:TITLE_CHARS],
        "file": _file_of(signature),
        "command": command_of_signature(signature),
        "sessions": sessions,
        "turnsPerOccurrence": turns,
        "minutesPerOccurrence": round(turns * MINUTES_PER_TURN, 1),
        "failure": failure_detail(latest.quote) or happened(signature),
        "fix": resolution_clause(latest) if latest.resolution else None,
        "lessonId": lesson_id(latest),
        # Raw text: the page escapes it when drawing. The model's summary leads; the rule-built one
        # fills in until the session's model has written one.
        "summary": scrub(review.summary) if review else "",
        "ruleSummary": rule_summary(latest),
    }


def _lesson(
    number: int,
    latest: Lesson,
    words: LessonContext | None,
    review: Review | None,
    annotated: frozenset[str],
) -> dict[str, Any]:
    """The lesson's fields: its note, the developer's words and the reviewer's verdict."""
    return {
        "id": lesson_id(latest),
        "painPointId": number,
        "confirmed": bool(latest.resolution or words or review),
        "verdict": review.verdict.value if review else None,
        "rule": review.rule if review else "",
        "reviewConflict": _conflict(lesson_id(latest), review, annotated),
        "appliesTo": _tags(words, review),
        "note": render_lesson(latest),
        "exampleContext": latest.quote[:200],
        "context": words.text if words else "",
        "intentional": words.intentional if words else False,
        "priority": words.priority.value if words else "normal",
    }


def _conflict(ident: str, review: Review | None, annotated: frozenset[str]) -> str | None:
    """The reviewer's silencing verdict on a lesson the developer annotated, else None.

    The lesson stays active (the developer's words outrank the model); the dashboard asks
    whether to keep it or dismiss it, and that choice wins.
    """
    if review is None or ident not in annotated or review.verdict is Verdict.MISTAKE:
        return None
    return review.verdict.value


def _tags(words: LessonContext | None, review: Review | None) -> dict[str, list[str]]:
    """The applicability tags in force: the developer's own, else the reviewer's."""
    own = words.applies if words else None
    chosen = own if own and (own.terms or own.areas) else (review.applies if review else None)
    return {
        "terms": list(chosen.terms) if chosen else [],
        "areas": list(chosen.areas) if chosen else [],
    }


def _written_point(
    number: int,
    item: AuthoredLesson,
    order: Mapping[str, tuple[int, date]],
    words: LessonContext | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A written lesson as a pain point: it has no sessions of its own, so it sits on the newest."""
    newest = max((index for index, _ in order.values()), default=0)
    kind = {"mistake": "repeat", "correction": "correction"}.get(item.kind.value, item.kind.value)
    point = {
        "id": number,
        "kind": kind,
        "title": item.text[:90],
        "file": item.files[0] if item.files else "",
        "command": None,
        "sessions": [newest],
        "turnsPerOccurrence": 1,
        "minutesPerOccurrence": MINUTES_PER_TURN,
        "failure": item.text,
        "fix": None,
        "lessonId": item.ident,
    }
    lesson = {
        "id": item.ident,
        "painPointId": number,
        "confirmed": True,
        "verdict": None,
        "rule": "",
        "reviewConflict": None,
        "appliesTo": {"terms": list(item.applies.terms), "areas": list(item.applies.areas)},
        "note": item.text,
        "exampleContext": "" if item.source_url else item.source_label,
        "sourceLabel": item.source_label,
        "sourceUrl": item.source_url,
        "context": words.text if words else "",
        "intentional": words.intentional if words else False,
        "priority": words.priority.value if words else _priority_of(item),
    }
    return point, lesson


def _priority_of(item: AuthoredLesson) -> str:
    """The priority a written lesson shows before the developer sets one."""
    return {"high": "high", "low": "low"}.get(item.severity.value, "normal")


def _file_of(signature: Signature) -> str:
    """The file or path the trouble is about, else the empty string."""
    first = signature.key[0] if signature.key else ""
    if signature.signal is Signal.FAILED_COMMAND:
        return signature.key[1] if len(signature.key) > 2 and signature.key[1] != "-" else ""
    return first if "/" in first or "." in first else ""


def command_of_signature(signature: Signature) -> str | None:
    """The command of a failed-command trouble, else None."""
    if signature.signal is not Signal.FAILED_COMMAND:
        return None
    return " ".join(part for part in signature.key[:-1] if part != "-") or None


def _replay(
    points: list[dict[str, Any]], day_of: Mapping[int, int], last_day: int
) -> dict[str, Any]:
    """Repeats in the last REPLAY_DAYS that a note would have come before (an estimate)."""
    start = max(0, last_day - REPLAY_DAYS)
    items = [
        {
            "painPointId": point["id"],
            "sessionIndex": index,
            "day": day_of[index],
            "turnsSaved": point["turnsPerOccurrence"],
            "minutesSaved": point["minutesPerOccurrence"],
        }
        for point in points
        for index in point["sessions"][1:]
        if day_of[index] >= start
    ]
    return {"windowStartDay": start, "items": sorted(items, key=lambda item: item["day"])}
