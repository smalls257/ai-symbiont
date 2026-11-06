"""Page data for the Pain points stage: themes, patterns, lessons ready and one session.

Themes, patterns and turns lost are decided in `miner/`; this
file only assembles them, in the order the sessions were mined, for `static/struggle.js` to scope
by one click. Every label that came from a record leaves through `scrub`.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from symbiont.core.notes import happened, resolution_clause
from symbiont.miner.churn import FileChurn
from symbiont.miner.lessons import Lesson
from symbiont.miner.patterns import HELP, NOTHING_TO_TEACH, StrugglePattern
from symbiont.miner.representatives import min_sessions_shown, theme_words
from symbiont.miner.screen import HoldReason
from symbiont.miner.secrets import scrub
from symbiont.miner.strips import Lane, SessionStrip
from symbiont.miner.struggle import (
    BURST_FAILURES,
    BURST_STEPS,
    MINUTES_PER_TURN,
    Outcome,
    SessionFacts,
    burst_spans,
)
from symbiont.miner.trained import lesson_id
from symbiont.store.held_back import held_back_sentence

FILES_SHOWN = 14
TITLE_CHARS = 90
TITLES_PER_THEME = 2
# (heading, short column head, what it means) per pattern, in the developer's words.
PATTERN_WORDS: Mapping[StrugglePattern, tuple[str, str, str]] = {
    StrugglePattern.TESTS_NOT_FOUND: (
        "Ran tests that do not exist",
        "Tests not found",
        "pytest collected nothing or was given a bad path or option (exit 4 or 5)",
    ),
    StrugglePattern.INLINE_TRIAL: (
        "Trial and error in inline scripts",
        "Inline trial",
        "three or more failing `python -c` or heredoc scripts",
    ),
    StrugglePattern.SCRATCH_DEBUG: (
        "Debugging in scratch files",
        "Scratch debug",
        "eight or more edits to throwaway files outside the codebase",
    ),
    StrugglePattern.EDIT_THRASH: (
        "Edit thrash",
        "Edit thrash",
        "the same source file edited five or more times",
    ),
    StrugglePattern.WRONG_API: (
        "Wrong API after an edit",
        "Wrong API",
        "AttributeError, TypeError or NameError right after an edit in the codebase",
    ),
    StrugglePattern.WRONG_PLACE: (
        "Looking in the wrong place",
        "Wrong place",
        "five or more probes (ls, find, cat, grep) that found nothing",
    ),
    StrugglePattern.RERUNNING: (
        "Re-running instead of fixing",
        "Re-running",
        "three or more failures that passed later with no edit between",
    ),
    StrugglePattern.ENDED_FAILING: (
        "Ended still failing",
        "Ended failing",
        "the last test run of the session failed",
    ),
}


@dataclass(frozen=True)
class StageInput:
    """What the stage is drawn from: the last mining's facts, strips and churn, and the lessons."""

    facts: Sequence[SessionFacts]
    strips: Sequence[SessionStrip]
    # The lessons as the pain-point list groups them (the reviewer's merges included), so a lesson
    # here is the same row there.
    groups: Sequence[Sequence[Lesson]]
    churn: Sequence[FileChurn]
    session_dates: Mapping[str, date]
    held_back: Mapping[HoldReason, int]
    min_sessions: int


def struggle_stage(view: StageInput, today: date) -> dict[str, Any] | None:
    """The stage's data, or None for a store mined before session facts existed."""
    facts = view.facts
    if not facts:
        return None
    index = {fact.session_id: i for i, fact in enumerate(facts)}
    lessons = _lessons_ready(view.groups, index)
    months = _months(facts, view.session_dates, today)
    return {
        "minutesPerTurn": MINUTES_PER_TURN,
        "minSessions": view.min_sessions,
        "burstFailures": BURST_FAILURES,
        "burstSteps": BURST_STEPS,
        "heldBack": held_back_sentence(view.held_back),
        "kpis": _kpis(facts, len(lessons)),
        "facts": [_fact(fact) for fact in facts],
        "patterns": _patterns(),
        "themeWords": theme_words(facts),
        "minThemeSessions": min_sessions_shown(len(facts)),
        "titles": _titles(facts),
        "lessons": lessons,
        "strips": _strips(view.strips, index),
        "files": _files(view.churn, index),
        **months,
    }


def _kpis(facts: Sequence[SessionFacts], lessons: int) -> dict[str, int]:
    """The unscoped totals; the page recomputes the same sums over a selection."""
    turns = sum(fact.turns_lost for fact in facts)
    failures = sum(sum(fact.outcomes.values()) for fact in facts)
    fixed = sum(
        fact.outcomes.get(kind, 0)
        for fact in facts
        for kind in (Outcome.CODE_FIX, Outcome.CORRECTED_COMMAND)
    )
    return {
        "turnsLost": turns,
        "minutes": round(turns * MINUTES_PER_TURN),
        "lessonsReady": lessons,
        "failures": failures,
        "knownFixes": fixed,
        "knownFixPercent": round(100 * fixed / failures) if failures else 0,
    }


def _fact(fact: SessionFacts) -> dict[str, Any]:
    return {
        "themes": sorted(fact.themes),
        "patterns": sorted(p.value for p in fact.patterns),
        "turns": fact.turns_lost,
        "struggled": fact.struggled,
        "outcomes": dict(fact.outcomes),
    }


def _patterns() -> list[dict[str, str | bool]]:
    return [
        {
            "id": p.value,
            "name": name,
            "short": short,
            "means": means,
            "help": HELP[p],
            "teachable": p not in NOTHING_TO_TEACH,
        }
        for p, (name, short, means) in PATTERN_WORDS.items()
    ]


def _titles(facts: Sequence[SessionFacts]) -> dict[str, list[str]]:
    """Up to two task labels per theme word, as examples."""
    titles: dict[str, list[str]] = defaultdict(list)
    for fact in facts:
        for word in fact.themes:
            if len(titles[word]) < TITLES_PER_THEME:
                titles[word].append(scrub(fact.task_label))
    return dict(titles)


def _lessons_ready(
    groups: Sequence[Sequence[Lesson]], index: Mapping[str, int]
) -> list[dict[str, Any]]:
    """One entry per pain-point row, with the sessions (by index) the trouble came back in."""
    ready = [_ready(group, index) for group in groups]
    return sorted(ready, key=lambda item: (-len(item["sessions"]), item["title"]))


def _ready(group: Sequence[Lesson], index: Mapping[str, int]) -> dict[str, Any]:
    latest = group[-1]
    sessions = sorted(
        {index[x.pain_point.session_id] for x in group if x.pain_point.session_id in index}
    )
    return {
        "id": lesson_id(latest),
        "title": scrub(happened(latest.pain_point.signature))[:TITLE_CHARS],
        "fix": scrub(resolution_clause(latest)) if latest.resolution else "",
        "sessions": sessions,
        "occurrences": len(group),
    }


def _strips(strips: Sequence[SessionStrip], index: Mapping[str, int]) -> dict[str, Any]:
    """The drawn sessions, keyed by their index among the facts."""
    return {str(index[s.session_id]): _strip(s) for s in strips if s.session_id in index}


def _strip(strip: SessionStrip) -> dict[str, Any]:
    failing = [s.step for s in strip.steps if s.lane is Lane.FAILED]
    return {
        "task": scrub(strip.task_label),
        "burst": strip.burst,
        "total": strip.total_steps,
        "bursts": [list(span) for span in burst_spans(failing)],
        "steps": [[s.step, s.lane.value, scrub(s.label)] for s in strip.steps],
    }


def _files(churn: Sequence[FileChurn], index: Mapping[str, int]) -> list[dict[str, Any]]:
    """The most edited files with the sessions (by index) that edited them."""
    edits: dict[str, int] = defaultdict(int)
    sessions: dict[str, set[int]] = defaultdict(set)
    for row in churn:
        edits[row.file] += row.edits
        if row.session_id in index:
            sessions[row.file].add(index[row.session_id])
    ranked = sorted(edits, key=lambda file: (-edits[file], file))[:FILES_SHOWN]
    return [{"file": f, "edits": edits[f], "sessions": sorted(sessions[f])} for f in ranked]


def _months(
    facts: Sequence[SessionFacts], dates: Mapping[str, date], today: date
) -> dict[str, Any]:
    """The months the sessions fall in (oldest first) and each session's month index."""
    labels = [_month(dates.get(fact.session_id, today)) for fact in facts]
    months = sorted(set(labels))
    return {"months": months, "monthOf": [months.index(label) for label in labels]}


def _month(when: date) -> str:
    return f"{when.year}-{when.month:02d}"
