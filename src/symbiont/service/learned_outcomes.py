"""What followed each step of a learned log: the pain points it hit, as the decider's outcomes."""

from typing import Any

from symbiont.core.features import featurise
from symbiont.core.slot import Decider, Outcome, Situation
from symbiont.miner.painpoint import PainPoint
from symbiont.records.schema import Record


def outcomes(record: Record, troubles: dict[tuple[str, int], list[PainPoint]]) -> list[Outcome]:
    """What followed a record: the pain points it hit, or a plain no-trouble outcome."""
    found = troubles.get((record.session_id, record.step), [])
    if not found:
        return [
            Outcome(
                pain_point_followed=False,
                signature=None,
                session_id=record.session_id,
                step=record.step,
            )
        ]
    return [
        Outcome(
            pain_point_followed=True, signature=p.signature, session_id=p.session_id, step=p.step
        )
        for p in found
    ]


def troubles_by_step(
    mined: list[PainPoint], records: list[Record]
) -> dict[tuple[str, int], list[PainPoint]]:
    """Pain points mined from the given sessions, keyed by (session, step)."""
    sessions = {r.session_id for r in records}
    by_step: dict[tuple[str, int], list[PainPoint]] = {}
    for pain in mined:
        if pain.session_id in sessions:
            by_step.setdefault((pain.session_id, pain.step), []).append(pain)
    return by_step


def replay_into_decider(
    decider: Decider,
    state: Any,
    history: tuple[PainPoint, ...],
    project: str,
    records: list[Record],
) -> tuple[int, Any]:
    """Replay one project's records through the decider; returns the count learned and the state."""
    troubles = troubles_by_step(list(history), records)
    mine = [r for r in records if r.project == project]
    for i, record in enumerate(mine):
        x = featurise(Situation(project, tuple(mine[: i + 1]), history, ()))
        for outcome in outcomes(record, troubles):
            state = decider.learn(x, outcome, state)
    return len(mine), state
