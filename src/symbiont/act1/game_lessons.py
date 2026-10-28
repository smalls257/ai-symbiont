"""Lessons from Freedoom play: what happened, how it was resolved, the check to run (pure).

Violation prevented: Leaky Narrative. A lesson is read by Glimmer (in training rows) and by people
(on the demo page), so it speaks the game text's language: rooms by the order the player entered
them, a heading as a compass word, moves as the model wrote them, and the observation's own line
names ("Doors", "Layout", "Reachable with go_to"). Coordinates, sector numbers and tag names never
appear. Violation prevented: Silent Fallback. A record from another harness, a pain or move this
module has no sentence for raises `LessonSourceError`; a mistake that nothing later fixed is
counted as unresolved, never given an invented resolution.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from symbiont.act1.game_pains import GamePain
from symbiont.records.schema import Record

HARNESS = "vizdoom"
PAIN_PREFIX = "pain:"
LABEL_PREFIX = "scripted "  # every move label says it was scripted; lessons quote the move itself
ORDINALS = ("start", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth")
COMPASS = ("east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast")
TIMES = {1: "once", 2: "twice"}
# A turn or a shot that drifts across a sector line did not take the player anywhere on purpose,
# so it is never credited with reaching a new room.
STANDING_VERBS = frozenset({"turn", "shoot_nearest"})

# Checks name the observation lines the model reads each decision (env_text.describe).
REENTERED_CHECK = (
    "Before leaving a room, pick a door, key or exit from 'Reachable with go_to' you have not "
    "reached yet; do not walk back into a room you already left unless that route runs through it."
)
RECHECKED_CHECK = (
    "Do not turn to look around a room you already scanned; "
    "pick a door, key or exit from 'Reachable with go_to' instead."
)
# (move verb, start of the script's outcome or "" for any) -> check. First match wins.
WALL_CHECKS = (
    ("go_to", "", "When go_to gets stuck at a wall, turn toward the side the Layout line calls "
     "open before trying again."),
    ("", "", "Before walking, read the Layout line: if it says wall close ahead, use go_to, "
     "which routes around walls."),
)  # fmt: skip
WASTED_CHECKS = (
    ("open_door", "", "Before open_door(), check that the Doors line lists a closed door close "
     "by; if none is listed, use go_to(door) instead."),
    ("go_to", "enemy in the way", "When go_to stops for an enemy in the way, shoot_nearest() "
     "first, then repeat the go_to."),
    ("go_to", "no key left", "Before go_to(key), check that 'Reachable with go_to' lists a key "
     "you do not hold yet."),
    ("go_to", "no path", "Before go_to, read 'Reachable with go_to': when it says no route or a "
     "locked door, fetch the key it names first."),
    ("go_to", "", "Before go_to, check that 'Reachable with go_to' lists the target."),
    ("shoot_nearest", "", "Before shoot_nearest(), check that the Visible line lists an enemy."),
    ("walk_to", "", "Before walk_to, check that the Visible line lists the target."),
    ("retreat_to", "", "Before retreat_to, check that the Visible line lists the target."),
    ("turn", "", "Turn toward a side the Layout line calls open; a turn that ends facing the "
     "same way wastes a decision."),
)  # fmt: skip


class LessonSourceError(ValueError):
    """The records cannot be turned into game lessons; the message names the record."""


@dataclass(frozen=True)
class GameLesson:
    """One mistake from play, how the episode got past it, and the habit that avoids it."""

    lesson_id: str
    level: str
    pain: GamePain
    repeats: int  # how many tagged moves the group holds; repeated mistakes are taught first
    what_happened: str
    how_resolved: str
    check: str

    def card(self) -> str:
        """The lesson as one line, in the Route B card's three parts."""
        return (
            f"What happened: {self.what_happened} How it was resolved: {self.how_resolved} "
            f"The check to run: {self.check}"
        )


@dataclass(frozen=True)
class LessonHarvest:
    """Lessons plus the counters a reader needs to trust them.

    `mistakes` counts every tagged move by pain (the demo's repeated-mistake counter); `unresolved`
    counts mistake groups that no later move got past, which are not turned into lessons.
    """

    lessons: tuple[GameLesson, ...]
    mistakes: Counter[str] = field(default_factory=Counter)
    unresolved: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class _Step:
    index: int
    move: str
    outcome: str
    room_before: int
    room_after: int | None
    angle: int
    keys: tuple[str, ...]
    ended: str | None
    pains: tuple[GamePain, ...]


@dataclass(frozen=True)
class _Group:
    pain: GamePain
    room: int
    move: str
    steps: tuple[_Step, ...]


def lessons_from_history(records: Iterable[Record]) -> LessonHarvest:
    """Lessons from every episode in `records`, grouped by session id in first-seen order."""
    episodes: dict[str, list[Record]] = {}
    for record in records:
        episodes.setdefault(record.session_id, []).append(record)
    harvests = [lessons_from_episode(episode) for episode in episodes.values()]
    return LessonHarvest(
        tuple(lesson for harvest in harvests for lesson in harvest.lessons),
        sum((harvest.mistakes for harvest in harvests), Counter()),
        sum((harvest.unresolved for harvest in harvests), Counter()),
    )


def lessons_from_episode(records: Sequence[Record]) -> LessonHarvest:
    """One lesson per repeated or single mistake group that a later move got past.

    A group is one pain in one room (and, for wall bumps and wasted moves, one move). Raises
    LessonSourceError for a non-vizdoom record, records from two episodes, or unparseable facts.
    """
    steps = [_step(record) for record in _one_episode(records)]
    rooms = _room_names(steps)
    progress = _progress(steps, rooms)
    lessons, unresolved = [], Counter[str]()
    for group in _groups(steps):
        resolution = next((progress[s.index] for s in steps[group.steps[-1].index + 1 :]
                           if progress[s.index]), None)  # fmt: skip
        if resolution is None:
            unresolved[group.pain.value] += 1
            continue
        lessons.append(_lesson(records[0], group, rooms, resolution))
    mistakes = Counter(pain.value for step in steps for pain in step.pains)
    return LessonHarvest(tuple(lessons), mistakes, unresolved)


def _one_episode(records: Sequence[Record]) -> Sequence[Record]:
    if not records:
        raise LessonSourceError("no records: an episode needs at least one played move")
    for position, record in enumerate(records):
        if record.step != position:
            raise LessonSourceError(f"{record.session_id}: step {record.step} is out of order")
        if record.harness != HARNESS:
            raise LessonSourceError(f"{record.session_id} step {record.step}: not a game record")
        if record.session_id != records[0].session_id:
            raise LessonSourceError(
                f"{record.session_id} and {records[0].session_id} are two episodes"
            )
    return records


def _step(record: Record) -> _Step:
    try:
        facts: dict[str, Any] = json.loads(record.raw)
        return _Step(
            index=record.step,
            move=(record.command or "").removeprefix(LABEL_PREFIX),
            outcome=facts["outcome"],
            room_before=int(facts["room_before"]),
            room_after=None if facts["room_after"] is None else int(facts["room_after"]),
            angle=int(facts["angle"]),
            keys=tuple(facts["keys_held"]),
            ended=facts["ended"],
            pains=tuple(GamePain(tag.removeprefix(PAIN_PREFIX)) for tag in record.tags
                        if tag.startswith(PAIN_PREFIX)),
        )  # fmt: skip
    except (KeyError, TypeError, ValueError) as error:
        raise LessonSourceError(f"{record.session_id} step {record.step}: {error}") from error


def _room_names(steps: Sequence[_Step]) -> dict[int, str]:
    """Rooms named by the order the player first stood in them; the map's numbers stay hidden."""
    order: list[int] = []
    for step in steps:
        for room in (step.room_before, step.room_after):
            if room is not None and room not in order:
                order.append(room)
    return {room: _ordinal_room(number) for number, room in enumerate(order)}


def _ordinal_room(number: int) -> str:
    if number == 0:
        return "the start room"
    if number < len(ORDINALS):
        return f"the {ORDINALS[number]} room you entered"
    return f"room {number + 1} in the order you entered them"


def _progress(steps: Sequence[_Step], rooms: dict[int, str]) -> dict[int, str | None]:
    """What each move achieved that moved the episode on, or None: exit, key, door, new room."""
    visited: set[int] = set()
    keys: set[str] = set()
    found: dict[int, str | None] = {}
    for step in steps:
        visited.add(step.room_before)
        new_keys = sorted(set(step.keys) - keys)
        found[step.index] = _achievement(step, new_keys, visited, rooms)
        keys.update(step.keys)
        if step.room_after is not None:
            visited.add(step.room_after)
    return found


def _achievement(
    step: _Step, new_keys: list[str], visited: set[int], rooms: dict[int, str]
) -> str | None:
    if step.ended == "exited":
        return f"`{step.move}` reached the exit and ended the level."
    if new_keys:
        return f"`{step.move}` picked up the {' and '.join(new_keys)} key."
    if step.outcome == "opened":
        return f"`{step.move}` opened a door."
    entered = step.room_after is not None and step.room_after not in visited
    if entered and _verb(step.move) not in STANDING_VERBS:
        return f"`{step.move}` took you into {rooms[step.room_after]}."
    return None


def _groups(steps: Sequence[_Step]) -> list[_Group]:
    """Mistakes grouped by pain and room (and move, where the move is the mistake)."""
    grouped: dict[tuple[GamePain, int, str], list[_Step]] = {}
    for step in steps:
        for pain in step.pains:
            grouped.setdefault(_group_key(pain, step), []).append(step)
    return [_Group(pain, room, move, tuple(found)) for (pain, room, move), found in grouped.items()]


def _group_key(pain: GamePain, step: _Step) -> tuple[GamePain, int, str]:
    if pain in (GamePain.WALL_BUMP, GamePain.WASTED_MOVE):
        return pain, step.room_before, step.move
    if step.room_after is None:
        raise LessonSourceError(f"step {step.index}: a {pain} tag on a move the episode ended in")
    return pain, step.room_after, ""


def _lesson(first: Record, group: _Group, rooms: dict[int, str], resolution: str) -> GameLesson:
    level = json.loads(first.raw)["level"]
    room = rooms[group.room]
    where = room.removeprefix("the ")
    return GameLesson(
        lesson_id=f"{first.session_id}/{group.pain.value}/{where}/{group.move}".rstrip("/"),
        level=level,
        pain=group.pain,
        repeats=len(group.steps),
        what_happened=_what_happened(group, room),
        how_resolved=resolution[0].upper() + resolution[1:],
        check=_check(group),
    )


def _what_happened(group: _Group, room: str) -> str:
    times = TIMES.get(len(group.steps), f"{len(group.steps)} times")
    if group.pain is GamePain.WALL_BUMP:
        heading = _compass(group.steps[0].angle)
        return f"`{group.move}` walked into a wall {times} in {room}, heading {heading}."
    if group.pain is GamePain.ROOM_REENTERED:
        return f"You went back into {room} {times} after leaving it."
    if group.pain is GamePain.ROOM_RECHECKED:
        return f"You turned to look around {room} {times} and saw nothing new."
    if group.pain is GamePain.WASTED_MOVE:
        reason = _outcome_head(group.steps[0].outcome)
        said = f": the script said {reason}" if reason else ""
        return f"`{group.move}` changed nothing {times} in {room}{said}."
    raise LessonSourceError(f"no sentence for pain {group.pain}")


def _compass(angle: int) -> str:
    """Freedoom's angle 0 faces east and 90 faces north; eight compass words."""
    return COMPASS[round((angle % 360) / 45) % len(COMPASS)]


def _outcome_head(outcome: str) -> str | None:
    """The script's own reason up to its details; None when even the head carries numbers."""
    head = re.split(r"[:(]", outcome)[0].strip()
    return None if not head or re.search(r"\d", head) else f'"{head}"'


def _check(group: _Group) -> str:
    if group.pain is GamePain.ROOM_REENTERED:
        return REENTERED_CHECK
    if group.pain is GamePain.ROOM_RECHECKED:
        return RECHECKED_CHECK
    table = WALL_CHECKS if group.pain is GamePain.WALL_BUMP else WASTED_CHECKS
    verb = _verb(group.move)
    outcome = group.steps[0].outcome
    for check_verb, reason, check in table:
        if check_verb in ("", verb) and outcome.startswith(reason):
            return check
    raise LessonSourceError(f"no check for {group.pain} after `{group.move}` ({outcome!r})")


def _verb(move: str) -> str:
    return move.split("(")[0]
