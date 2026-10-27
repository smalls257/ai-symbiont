"""Dashboard export: one JSON the static page reads.

Schema v0, to be aligned with Task 15 (the event log does not exist yet, and
neither does the Act 2 runner). The dataclasses below are the contract this
file defines in the meantime; when Task 15 lands, an adapter maps its log onto
these and nothing in the page changes.

Violation prevented: **Paper Tiger**. A race or scoreboard that shows the fly
alone meets the layout and fails the claim, so the export refuses a fly lane
or row without a counters companion directly beside it, and refuses any lane
or row whose role label is not one of floor / ceiling / reference / under test.
Every lane, row and panel also carries a claim tag (measured / established /
hypothesis), so a number cannot be shown without saying how much to trust it.

Second guard, **Black Box**: the brain panel is only honest if it shows what
the learner did each step, so a snapshot must carry exactly 259 active cells
out of 5,177 and a learn flag, and there must be one snapshot per step of the
session (a shorter brain would be shown as if current). It carries no feature
names and no scores, so the page cannot show them as notes.

Third guard, **Infected Core**: a pure transform. Nothing here reads a file,
a clock or a network; the caller loads the log and writes the JSON.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SCHEMA = "dashboard-v0"
SCHEMA_NOTE = "v0, to be aligned with Task 15 (event log); inputs are provisional."
CELLS = 5177
ACTIVE_PER_STEP = 259
ROLES = ("floor", "ceiling", "reference", "under test")
STATUSES = ("measured", "established", "hypothesis")
FLY_KEY = "fly"
COUNTERS_KEY = "counters"
# Act 1 is Freedoom, Act 2 is the coding "developer's week".
ACTS = ("freedoom", "coding")


class SchemaViolationError(ValueError):
    """The input does not meet the v0 contract; the page must not render it."""


@dataclass(frozen=True)
class TimelineEvent:
    """One step of a session.

    `repeat` is True when the step repeats an earlier mistake (same failing
    command, same reworked edit); the page marks it red.
    """

    step: int
    kind: str
    label: str
    repeat: bool


@dataclass(frozen=True)
class LedgerLine:
    """Spend at step `step` (not cumulative): tokens and dollars for that step."""

    step: int
    tokens: int
    dollars: float


@dataclass(frozen=True)
class LaneInput:
    """One racing session.

    `lane_id` is the arm key ("plain", "counters", "fly"); `role` is one of
    ROLES; `status` is one of STATUSES.
    """

    lane_id: str
    label: str
    role: str
    status: str
    events: Sequence[TimelineEvent]
    ledger: Sequence[LedgerLine]


@dataclass(frozen=True)
class PainPointCount:
    """Pain points the miner found in one file (repo fault map)."""

    path: str
    count: int


@dataclass(frozen=True)
class LearnerSnapshot:
    """What the learner did at step `step`.

    Which of the 5,177 cells fired, and whether a learn event (the
    dopamine-like signal) happened on that step.
    """

    step: int
    active_cells: Sequence[int]
    learned: bool


@dataclass(frozen=True)
class ScoreRow:
    """A scoreboard row.

    `key` identifies the arm ("plain", "counters", "fly"); `role` is one of
    ROLES; `status` is one of STATUSES; `value` is display text, never
    recomputed here.
    """

    key: str
    label: str
    role: str
    status: str
    value: str


@dataclass(frozen=True)
class DashboardInput:
    """Everything the page shows for one act, before validation."""

    act: str
    lanes: Sequence[LaneInput]
    pain_points: Sequence[PainPointCount]
    snapshots: Sequence[LearnerSnapshot]
    scoreboard: Sequence[ScoreRow]
    fault_status: str
    brain_status: str
    source: str = ""  # where the numbers came from, e.g. "synthetic replay"


def _check_label(kind: str, key: str, role: str, status: str) -> None:
    if role not in ROLES:
        raise SchemaViolationError(f"{kind} {key!r}: role {role!r} is not one of {ROLES}")
    _check_status(f"{kind} {key!r}", status)


def _check_status(where: str, status: str) -> None:
    if status not in STATUSES:
        raise SchemaViolationError(f"{where}: status {status!r} is not one of {STATUSES}")


def _check_counters_beside_fly(kind: str, keys: Sequence[str]) -> None:
    if FLY_KEY not in keys:
        return
    if COUNTERS_KEY not in keys:
        raise SchemaViolationError(
            f"the fly {kind} needs a counters {kind} beside it; the counters {kind} is missing"
        )
    if abs(keys.index(FLY_KEY) - keys.index(COUNTERS_KEY)) != 1:
        raise SchemaViolationError(f"the counters {kind} must sit directly beside the fly {kind}")


def _lane_out(lane: LaneInput) -> dict[str, Any]:
    marks = [event.step for event in lane.events if event.repeat]
    tokens = 0
    dollars: float = 0
    fuel = []
    for line in sorted(lane.ledger, key=lambda entry: entry.step):
        tokens += line.tokens
        dollars += line.dollars
        fuel.append({"t": line.step, "tokens": tokens, "dollars": dollars})
    return {
        "id": lane.lane_id,
        "label": lane.label,
        "role": lane.role,
        "status": lane.status,
        "events": [
            {"t": ev.step, "kind": ev.kind, "label": ev.label, "repeat": ev.repeat}
            for ev in lane.events
        ],
        "repeat_marks": marks,
        "repeat_count": len(marks),
        "fuel": fuel,
        "totals": {"tokens": tokens, "dollars": dollars},
    }


def _lanes_out(lanes: Sequence[LaneInput]) -> list[dict[str, Any]]:
    if not lanes:
        raise SchemaViolationError("lanes: at least one session is needed")
    for lane in lanes:
        _check_label("lane", lane.lane_id, lane.role, lane.status)
    _check_counters_beside_fly("lane", [lane.lane_id for lane in lanes])
    return [_lane_out(lane) for lane in lanes]


def _brain_out(snapshots: Sequence[LearnerSnapshot], steps_in_session: int) -> dict[str, Any]:
    if len(snapshots) != steps_in_session:
        raise SchemaViolationError(
            f"snapshots: expected one per step ({steps_in_session}), got {len(snapshots)}"
        )
    steps = []
    for snap in snapshots:
        cells = list(snap.active_cells)
        if len(cells) != ACTIVE_PER_STEP or len(set(cells)) != ACTIVE_PER_STEP:
            raise SchemaViolationError(
                f"step {snap.step}: expected {ACTIVE_PER_STEP} distinct active cells, "
                f"got {len(set(cells))}"
            )
        if any(not 0 <= cell < CELLS for cell in cells):
            raise SchemaViolationError(f"step {snap.step}: cell index out of range 0..{CELLS - 1}")
        steps.append({"t": snap.step, "active": sorted(cells), "learned": snap.learned})
    return {"cells": CELLS, "active_per_step": ACTIVE_PER_STEP, "steps": steps}


def _scoreboard_out(rows: Sequence[ScoreRow]) -> list[dict[str, str]]:
    keys = [row.key for row in rows]
    missing = [key for key in (COUNTERS_KEY, FLY_KEY) if key not in keys]
    if missing:
        raise SchemaViolationError(
            "the scoreboard needs the counters row beside the fly row; "
            f"missing: {', '.join(missing)}"
        )
    _check_counters_beside_fly("row", keys)
    for row in rows:
        _check_label("row", row.key, row.role, row.status)
    return [
        {
            "key": row.key,
            "label": row.label,
            "role": row.role,
            "status": row.status,
            "value": row.value,
        }
        for row in rows
    ]


def export_dashboard(data: DashboardInput) -> Mapping[str, Any]:
    """Turn the v0 inputs into the JSON document the dashboard page reads."""
    if data.act not in ACTS:
        raise SchemaViolationError(f"act {data.act!r} is not one of {ACTS}")
    if not data.pain_points:
        raise SchemaViolationError("pain points: the fault map needs at least one file")
    _check_status("fault map", data.fault_status)
    _check_status("brain", data.brain_status)
    lanes = _lanes_out(data.lanes)
    steps = max(len(lane["events"]) for lane in lanes)
    faults = sorted(data.pain_points, key=lambda fault: (-fault.count, fault.path))
    return {
        "schema": SCHEMA,
        "note": SCHEMA_NOTE,
        "act": data.act,
        "source": data.source,
        "panel_status": {"fault_map": data.fault_status, "brain": data.brain_status},
        "lanes": lanes,
        "fault_map": [{"path": p.path, "pain_points": p.count} for p in faults],
        "brain": _brain_out(data.snapshots, steps),
        "scoreboard": _scoreboard_out(data.scoreboard),
    }
