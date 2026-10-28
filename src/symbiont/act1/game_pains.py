"""Game pain tags for an episode's moves (pure: positions, views and outcome text only).

Prevents Paper Tiger in the episode log: a tag that fires on almost every step, or on an event it
does not name (a lost target or a locked door called a wall), gives a meta-trainer nothing to learn
from. Each rule fires on the one event its name states and is paired with a near-miss test.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from symbiont.act1.env_text import GameStateView, normalize_degrees
from symbiont.act1.goto import STUCK_MIN_PROGRESS_UNITS
from symbiont.act1.moves import TURN_TOLERANCE_DEG
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveKind, MoveRun

# The distance go_to itself calls "made no progress"; a second definition would drift from it.
STILL_UNITS = STUCK_MIN_PROGRESS_UNITS

# The scripts' own outcome texts (WalkTo in moves.py, go_to in goto.py). Matching the text, not a
# distance, keeps a lost target or a locked door from being labeled a wall.
WALL_OUTCOMES = ("blocked by a wall", "stuck at")


class GamePain(StrEnum):
    """Pain points of play, declared in the order tags are listed within a run."""

    WALL_BUMP = "wall_bump"
    ROOM_REENTERED = "room_reentered"
    ROOM_RECHECKED = "room_rechecked"
    WASTED_MOVE = "wasted_move"


@dataclass
class _EpisodeMemory:
    left: set[int] = field(default_factory=set)
    turned_in: set[int] = field(default_factory=set)
    seen: dict[int, set[str]] = field(default_factory=dict)


def _names(view: GameStateView) -> set[str]:
    names = {item.name for item in view.objects}
    for door in view.doors:
        names.add("door" if door.key_colour is None else f"door ({door.key_colour})")
    for exit_ in view.exits:
        names.add("secret exit" if exit_.secret else "exit")
    return names


def _is_wall_bump(run: MoveRun) -> bool:
    return run.kind == MoveKind.WALK and run.tics >= 1 and run.outcome.startswith(WALL_OUTCOMES)


def _is_room_reentered(room_before: int, room_after: int, memory: _EpisodeMemory) -> bool:
    return room_after != room_before and room_after in memory.left


def _is_room_rechecked(
    kind: MoveKind, after: GameStateView, room_after: int, memory: _EpisodeMemory
) -> bool:
    if kind != MoveKind.TURN or room_after not in memory.turned_in:
        return False
    return _names(after) <= memory.seen.get(room_after, set())


def _is_wasted_move(before: GameStateView, after: GameStateView) -> bool:
    covered = math.dist(before.position, after.position)
    turned = abs(normalize_degrees(after.angle_deg - before.angle_deg))
    return (
        covered < STILL_UNITS
        and turned < TURN_TOLERANCE_DEG
        and before.health == after.health
        and before.ammo == after.ammo
        and before.keys_held == after.keys_held
        and before.closed_sectors == after.closed_sectors
    )


def _tag_one(run: MoveRun, rooms: RoomFinder, memory: _EpisodeMemory) -> tuple[GamePain, ...]:
    """Tags for one run, then the memory update the later runs' rules read."""
    room_before = rooms.room_at(run.before.position)
    memory.seen.setdefault(room_before, set()).update(_names(run.before))
    if run.after is None:
        return ()
    room_after = rooms.room_at(run.after.position)
    fired = {
        GamePain.WALL_BUMP: _is_wall_bump(run),
        GamePain.ROOM_REENTERED: _is_room_reentered(room_before, room_after, memory),
        GamePain.ROOM_RECHECKED: _is_room_rechecked(run.kind, run.after, room_after, memory),
        GamePain.WASTED_MOVE: _is_wasted_move(run.before, run.after),
    }
    if room_after != room_before:
        memory.left.add(room_before)
    if run.kind == MoveKind.TURN:
        memory.turned_in.add(room_after)
    memory.seen.setdefault(room_after, set()).update(_names(run.after))
    return tuple(pain for pain, did_fire in fired.items() if did_fire)


def tag_pains(runs: Sequence[MoveRun], rooms: RoomFinder) -> list[tuple[GamePain, ...]]:
    """One tuple of pain tags per run, in run order and enum order.

    Raises RoomLookupError when a position is inside no sector: a silent "unknown room" would hide
    re-entries. A run whose `after` is None (the episode ended in it) gets no tags.
    """
    memory = _EpisodeMemory()
    return [_tag_one(run, rooms, memory) for run in runs]
