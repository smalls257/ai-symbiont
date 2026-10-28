"""Played moves as common Records (pure: views, pains and room lookups only).

Prevents Leaky Narrative between Act 1 and the meta-trainer: the trainer reads only `Record`s, so
the episode log hands it the schema's own shape (a command, its tags, the facts in `raw`) rather
than a second format. A position in no room raises `RoomLookupError`; it is never logged as room
"unknown" (Silent Fallback).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from symbiont.act1.env_text import GameStateView
from symbiont.act1.game_pains import GamePain, tag_pains
from symbiont.act1.levels import WAD_PROJECT
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveRun
from symbiont.records.schema import Kind, Provenance, Record

# Spark-safe because the records are generated self-play on BSD-3 Freedoom levels and hold no
# user text or private content.
PROVENANCE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)


@dataclass(frozen=True)
class Episode:
    """One played level under one policy and seed."""

    level: str
    policy: str
    seed: int

    @property
    def session_id(self) -> str:
        """The record session id; level, policy and seed together name one replayable episode."""
        return f"{self.level}-{self.policy}-s{self.seed}"


def episode_records(episode: Episode, runs: Sequence[MoveRun], rooms: RoomFinder) -> list[Record]:
    """One command Record per run, in run order; raises RoomLookupError for an off-map position."""
    pains = tag_pains(runs, rooms)
    return [
        _record(episode, step, run, run_pains, rooms)
        for step, (run, run_pains) in enumerate(zip(runs, pains, strict=True))
    ]


def _record(
    episode: Episode, step: int, run: MoveRun, pains: tuple[GamePain, ...], rooms: RoomFinder
) -> Record:
    return Record(
        harness="vizdoom",
        project=WAD_PROJECT,
        session_id=episode.session_id,
        step=step,
        kind=Kind.COMMAND,
        raw=json.dumps(_facts(episode, run, rooms), sort_keys=True),
        provenance=PROVENANCE,
        command=run.label,
        exit_code=None,
        task_id=None,
        tags=(f"policy:{episode.policy}", *(f"pain:{pain}" for pain in pains)),
    )


def _facts(episode: Episode, run: MoveRun, rooms: RoomFinder) -> dict[str, Any]:
    latest = run.before if run.after is None else run.after
    return {
        "level": episode.level,
        "policy": episode.policy,
        "seed": episode.seed,
        "decision": run.decision,
        "position_before": _rounded(run.before),
        "position_after": None if run.after is None else _rounded(run.after),
        "room_before": rooms.room_at(run.before.position),
        "room_after": None if run.after is None else rooms.room_at(run.after.position),
        "angle": round(latest.angle_deg),
        "health": latest.health,
        "ammo": latest.ammo,
        "keys_held": list(latest.keys_held),
        "tics": run.tics,
        "outcome": run.outcome,
    }


def _rounded(view: GameStateView) -> list[int]:
    x, y = view.position
    return [round(x), round(y)]
