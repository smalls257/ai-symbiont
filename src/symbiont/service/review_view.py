"""The `reviews` key of the dashboard data: what reviewers flagged, grouped by what they said.

Review lessons (a comment a reviewer made that a later edit answered) are grouped by shared
distinctive words of the comment, with the same grouping that finds repeated rules. A dismissal
follows the group's member comments, not only its key, because a re-mine can rename a group.
Gists are scrubbed here again.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.triage import GroupState
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.fix_words import edit_clause, resolution_phrase
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.miner.rule_candidates import RuleCandidate
from symbiont.miner.rule_groups import group_by_terms
from symbiont.miner.rule_terms import salient_terms
from symbiont.miner.trained import lesson_id
from symbiont.service.rule_view import REVIEW_KEY_PREFIX, RuleEntry, Triaged, triage_outcome
from symbiont.store.local import Store

KEY_PREFIX = REVIEW_KEY_PREFIX
MAX_GIST_CHARS = 160
MAX_EXAMPLES = 3
# Lists on one row stay short; the group's count still says how many comments stand behind it.
MAX_LISTED = 5
SOURCE = "review_flag"
SENTENCE_END = (".", "!", "?")
Ref = tuple[str, int]


@dataclass(frozen=True)
class ReviewGroup:
    """Review lessons that say the same thing; `key` names the smallest member signature."""

    key: str
    members: tuple[Lesson, ...]

    @property
    def refs(self) -> tuple[Ref, ...]:
        """The (session, step) of each distinct comment."""
        return tuple(sorted({_ref(m) for m in self.members}))


def reviews_listing(store: Store, project: str, dates: Mapping[str, date]) -> dict[str, Any]:
    """The snapshot's `reviews` for `project`."""
    triage = store.review.triage
    dismissed = [k for k, row in triage.all(project).items() if row.state is GroupState.ARCHIVED]
    triaged = Triaged(dismissed, (), triage.members_by_key(project))
    return reviews_snapshot(store.lessons(project), dates, triaged)


def stored_review_refs(store: Store, project: str, key: str) -> tuple[Ref, ...]:
    """The comments the group `key` stands for now; () when no group has that key any more."""
    return review_member_refs(store.lessons(project), key)


def review_member_refs(lessons: Sequence[Lesson], key: str) -> tuple[Ref, ...]:
    """The (session, step) of each comment in the group `key`; () for an unknown key."""
    return next((g.refs for g in review_groups(lessons) if g.key == key), ())


def review_groups(lessons: Sequence[Lesson]) -> list[ReviewGroup]:
    """Review lessons that name a gist, grouped by shared distinctive words of the gist."""
    by_candidate = {_candidate(lesson): lesson for lesson in lessons if _gist_of(lesson)}
    groups = group_by_terms(list(by_candidate))
    found = [tuple(by_candidate[member] for member in group.members) for group in groups]
    return [ReviewGroup(_key_of(members), members) for members in found]


def reviews_snapshot(
    lessons: Sequence[Lesson], dates: Mapping[str, date], triaged: Triaged
) -> dict[str, Any]:
    """Groups seen in most sessions first; dismissed groups are counted and left out."""
    own = triaged.of_prefix(KEY_PREFIX)
    shown: list[dict[str, Any]] = []
    dismissed = 0
    for group in review_groups(lessons):
        if triage_outcome(RuleEntry(group.key, "", "repo", "", group.refs), own) is None:
            dismissed += 1
        else:
            shown.append(_item(group, dates))
    shown.sort(key=lambda item: item["key"])
    shown.sort(key=lambda item: item["last"] or "", reverse=True)
    shown.sort(key=lambda item: item["count"], reverse=True)
    shown.sort(key=lambda item: item["sessions"], reverse=True)
    return {"groups": shown, "dismissed": dismissed}


def _ref(lesson: Lesson) -> Ref:
    return (lesson.pain_point.session_id, lesson.pain_point.step)


def _key_tuple(lesson: Lesson) -> tuple[str, ...]:
    return lesson.pain_point.signature.key


def _gist_of(lesson: Lesson) -> str:
    key = _key_tuple(lesson)
    if lesson.pain_point.signature.signal is not Signal.REVIEW_FLAG or len(key) < 3:
        return ""
    return key[2]


def _candidate(lesson: Lesson) -> RuleCandidate:
    session_id, step = _ref(lesson)
    terms = salient_terms(_gist_of(lesson))
    return RuleCandidate(session_id, step, "|".join(_key_tuple(lesson)), terms, SOURCE)


def _key_of(members: Sequence[Lesson]) -> str:
    return KEY_PREFIX + scrub("|".join(min(_key_tuple(m) for m in members)))


def _item(group: ReviewGroup, dates: Mapping[str, date]) -> dict[str, Any]:
    keys = [_key_tuple(m) for m in group.members]
    days = sorted(dates[sid] for sid, _ in group.refs if sid in dates)
    return {
        "key": group.key,
        "gist": _quote(_headline([k[2] for k in keys])),
        "count": len(group.members),
        "sessions": len({sid for sid, _ in group.refs}),
        "reviewers": sorted({k[1] for k in keys}),
        "files": _distinct(sorted(k[0] for k in keys)),
        "fixedBy": _distinct(_edited(m) for m in group.members),
        "examples": _examples(group, dates),
        "lessonIds": [lesson_id(m) for m in group.members],
        "last": days[-1].isoformat() if days else None,
    }


def _headline(gists: Sequence[str]) -> str:
    """The shortest gist that ends in sentence punctuation, else the shortest: no dangling cut."""
    whole = [gist for gist in gists if gist.rstrip().endswith(SENTENCE_END)]
    return min(whole or gists, key=lambda gist: (len(gist), gist))


def _distinct(names: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(name for name in names if name))[:MAX_LISTED]


def _edited(lesson: Lesson) -> str:
    return edit_clause(resolution_phrase(lesson.resolution))


def _examples(group: ReviewGroup, dates: Mapping[str, date]) -> list[dict[str, Any]]:
    """Up to three comments, newest first; undated ones last."""

    def newest(lesson: Lesson) -> tuple[date, str, int]:
        session_id, step = _ref(lesson)
        return (dates.get(session_id, date.min), session_id, step)

    ordered = sorted(group.members, key=newest, reverse=True)[:MAX_EXAMPLES]
    return [_example(m, dates.get(_ref(m)[0])) for m in ordered]


def _example(lesson: Lesson, day: date | None) -> dict[str, Any]:
    path, _, gist = _key_tuple(lesson)[:3]
    session_id, step = _ref(lesson)
    date_text = None if day is None else day.isoformat()
    return {
        "gist": _quote(gist),
        "file": path,
        "sessionId": session_id,
        "step": step,
        "date": date_text,
    }


def _quote(text: str) -> str:
    """One line, credential-free, capped: scrubbed at the moment it enters the snapshot."""
    return " ".join(scrub(text).split())[:MAX_GIST_CHARS]
