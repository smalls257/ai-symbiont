"""One Freedoom episode pair as a `demo-replay-v1` file: plain and personal Glimmer side by side.

One step per model decision, in the schema the demo page already replays. `mistake_tag` and
`wasted` come from the records' pain tags joined by decision and totals are summed from steps,
never typed; the plain run has no adapter, and no note or adapter picker is emitted (Act 1
delivers none). Pure: decision log and episode records in, a dict out.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from symbiont.act1.game_pains import GamePain
from symbiont.act1.steplog import Decision
from symbiont.records.schema import Record

SCHEMA = "demo-replay-v1"
ACTION_MAX_WORDS = 12  # the demo contract's limit for a step label
ROLES = {"plain": "floor", "personal": "under test"}
STATUSES = ("measured", "established", "hypothesis")
PAIN_PREFIX = "pain:"


class ReplayError(ValueError):
    """The episode cannot be shown honestly (for example, a plain run with an adapter)."""


@dataclass(frozen=True)
class ArmEpisode:
    """One arm's played episode: who played, its decisions, its records and how it ended."""

    arm: str  # "plain" or "personal"
    label: str
    model: str
    adapter: str | None
    decisions: Sequence[Decision]
    records: Sequence[Record]


@dataclass(frozen=True)
class ReplayTask:
    """The level and seed both arms played, and where the files came from."""

    level: str
    seed: int
    source: str
    status: str


def demo_replay(task: ReplayTask, plain: ArmEpisode, personal: ArmEpisode) -> dict[str, Any]:
    """The demo-replay-v1 document. Raises ReplayError for a run the page must not show."""
    if task.status not in STATUSES:
        raise ReplayError(f"status {task.status!r} is not one of {STATUSES}")
    if (plain.arm, personal.arm) != ("plain", "personal"):
        raise ReplayError("runs must be plain then personal")
    if plain.adapter is not None:
        raise ReplayError("the plain run is the floor: it has no adapter")
    return {
        "schema": SCHEMA,
        "status": task.status,
        "source": task.source,
        "task": {
            "id": f"{task.level}-s{task.seed}",
            "repo": "freedoom2",
            "label": f"Freedoom {task.level}, seed {task.seed} (plays Freedoom via ViZDoom)",
        },
        "runs": [_run(plain, task.status), _run(personal, task.status)],
    }


def _run(episode: ArmEpisode, status: str) -> dict[str, Any]:
    pains = _pains_by_decision(episode.records)
    ended = _ended(episode.records)
    last = len(episode.decisions) - 1
    seen: set[tuple[str, str]] = set()
    steps = [
        _step(decision, pains.get(decision.index, ()), seen, ended if n == last else None)
        for n, decision in enumerate(episode.decisions)
    ]
    if not steps:
        raise ReplayError(f"the {episode.arm} run has no decisions")
    return {
        "id": episode.arm,
        "label": episode.label,
        "role": ROLES[episode.arm],
        "status": status,
        "model": episode.model,
        "adapter": episode.adapter,
        "steps": steps,
        "totals": _totals(steps, ended),
    }


def _pains_by_decision(records: Sequence[Record]) -> dict[int, tuple[tuple[str, str], ...]]:
    """(pain, what it was about) per decision; the move names a wasted move or wall bump."""
    found: dict[int, list[tuple[str, str]]] = {}
    for record in records:
        facts = json.loads(record.raw)
        for tag in record.tags:
            if tag.startswith(PAIN_PREFIX):
                pain = tag.removeprefix(PAIN_PREFIX)
                about = _about(GamePain(pain), record, facts)
                found.setdefault(int(facts["decision"]), []).append((pain, about))
    return {decision: tuple(pains) for decision, pains in found.items()}


def _about(pain: GamePain, record: Record, facts: dict[str, Any]) -> str:
    if pain in (GamePain.WALL_BUMP, GamePain.WASTED_MOVE):
        return f"{record.command} in {facts['room_before']}"
    return f"room {facts['room_after']}"


def _ended(records: Sequence[Record]) -> str:
    if not records:
        raise ReplayError("an episode with no records cannot be replayed")
    return str(json.loads(records[-1].raw)["ended"])


def _step(
    decision: Decision,
    pains: tuple[tuple[str, str], ...],
    seen: set[tuple[str, str]],
    ended: str | None,
) -> dict[str, Any]:
    repeated = any(pain in seen for pain in pains)
    seen.update(pains)
    return {
        "step": decision.index + 1,
        "action": _action(decision),
        "outcome": _outcome(decision, pains, ended),
        "tokens_in": decision.tokens_in or 0,  # None: a scripted policy called no model
        "tokens_out": decision.tokens_out or 0,
        "wall_s": round(decision.model_seconds, 2),
        "mistake_tag": "repeated" if repeated else "new" if pains else "none",
        "wasted": any(pain == GamePain.WASTED_MOVE for pain, _ in pains),
        "note": None,
        "classifier": None,
        "picker": None,
    }


def _action(decision: Decision) -> str:
    if decision.status != "ok":
        return f"reply {decision.status}: no move played"
    moves = [outcome.split(" -> ")[0] for outcome in decision.outcomes]
    words = ", ".join(moves).split()
    return " ".join(words[:ACTION_MAX_WORDS])


def _outcome(decision: Decision, pains: tuple[tuple[str, str], ...], ended: str | None) -> str:
    """Solved on the exit; failed on a tagged mistake, a rejected reply, a death or a timeout."""
    if ended == "exited":
        return "solved"
    lost = ended in ("died", "timed_out")
    return "failed" if pains or lost or decision.status != "ok" else "progress"


def _totals(steps: list[dict[str, Any]], ended: str) -> dict[str, Any]:
    return {
        "steps": len(steps),
        "tokens_in": sum(step["tokens_in"] for step in steps),
        "tokens_out": sum(step["tokens_out"] for step in steps),
        "wall_s": round(sum(step["wall_s"] for step in steps), 2),
        "repeated_mistakes": sum(step["mistake_tag"] == "repeated" for step in steps),
        "new_mistakes": sum(step["mistake_tag"] == "new" for step in steps),
        "wasted_steps": sum(step["wasted"] for step in steps),
        "notes": 0,
        "result": "solved" if ended == "exited" else "not solved",
    }
