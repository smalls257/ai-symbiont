"""Write the synthetic replay files the dashboard plays for video capture.

Run: uv run python scripts/make_dashboard_sample.py

The data is invented to exercise every panel; it is layout material, not a
result, and every claim in it is tagged hypothesis. Violation prevented:
**Paper Tiger**. A sample where the fly arm wins would be filmed as a result,
so every lane draws its repeats at the same rate from its own seeded random
stream: who ends up with fewer repeats is arbitrary, and the page says so.
Output goes through `export_dashboard`, so a sample that breaks the v0
contract cannot be written.
"""

import json
import random
from pathlib import Path

from symbiont.eval.export_dashboard import (
    ACTIVE_PER_STEP,
    CELLS,
    DashboardInput,
    LaneInput,
    LearnerSnapshot,
    LedgerLine,
    PainPointCount,
    ScoreRow,
    TimelineEvent,
    export_dashboard,
)

OUT = Path(__file__).resolve().parents[1] / "dashboard" / "sample"
STEPS = 48
REPEAT_RATE = 0.2  # identical for every arm: no lane is built to win
SOURCE = "synthetic replay, layout only; outcomes are arbitrary, no arm is built to win"
TAG = "hypothesis"


def _row(key: str, label: str, role: str) -> ScoreRow:
    return ScoreRow(key, label, role, TAG, "synthetic")


FREEDOOM = {
    "kinds": ["look", "move", "turn", "shoot", "move", "turn"],
    "labels": {"look": "read the room", "move": "move", "turn": "turn", "shoot": "shoot"},
    "faults": {
        "corridor north": 8,
        "door, red key": 7,
        "nukage pit": 5,
        "stair room": 4,
        "start room": 2,
        "exit hall": 1,
    },
    "lanes": (
        ("plain", "Muse Spark, plain", "floor"),
        ("counters", "Muse Spark + counters only", "reference"),
        ("fly", "Muse Spark + fly", "under test"),
    ),
    "rows": (
        _row("plain", "Muse Spark, plain", "floor"),
        _row("counters", "Muse Spark + counters only", "reference"),
        _row("fly", "Muse Spark + fly", "under test"),
    ),
}
CODING = {
    "kinds": ["read", "edit", "test", "edit", "test", "shell"],
    "labels": {
        "read": "read file",
        "edit": "edit file",
        "test": "run tests",
        "shell": "run command",
    },
    "faults": {
        "src/parser/lexer.py": 9,
        "src/parser/dialect.py": 7,
        "src/planner/rewrite.py": 6,
        "tests/test_lexer.py": 4,
        "src/executor/join.py": 3,
        "src/util/quote.py": 2,
        "docs/conf.py": 1,
    },
    "lanes": (
        ("plain", "Muse Glimmer, plain", "floor"),
        ("counters", "Muse Glimmer + counters only", "reference"),
        ("fly", "Muse Glimmer + fly (Route A)", "under test"),
    ),
    "rows": (
        _row("plain", "Muse Glimmer, plain", "floor"),
        _row("counters", "Muse Glimmer + counters only", "reference"),
        _row("fly", "Muse Glimmer + fly (Route A)", "under test"),
        _row("lora", "Muse Glimmer + personal LoRA (Route B)", "under test"),
        _row("wonder", "Muse Wonder, plain (cost story)", "reference"),
    ),
}


def _lane(rng: random.Random, spec: dict, lane_id: str, label: str, role: str) -> LaneInput:
    events, ledger = [], []
    for t in range(STEPS):
        kind = spec["kinds"][t % len(spec["kinds"])]
        repeat = t > 6 and rng.random() < REPEAT_RATE
        text = spec["labels"][kind] + (" (same as before)" if repeat else "")
        events.append(TimelineEvent(t, kind, text, repeat))
        tokens = rng.randint(900, 2600) + (1400 if repeat else 0)
        ledger.append(LedgerLine(t, tokens, round(tokens * 0.000006, 6)))
    return LaneInput(lane_id, label, role, TAG, tuple(events), tuple(ledger))


def _snapshots(rng: random.Random) -> tuple[LearnerSnapshot, ...]:
    return tuple(
        LearnerSnapshot(t, tuple(rng.sample(range(CELLS), ACTIVE_PER_STEP)), t % 7 == 6)
        for t in range(STEPS)
    )


def build(act: str, spec: dict, seed: int) -> dict:
    lanes = tuple(
        _lane(random.Random(seed * 100 + i), spec, *lane) for i, lane in enumerate(spec["lanes"])
    )
    data = DashboardInput(
        act=act,
        lanes=lanes,
        pain_points=tuple(PainPointCount(p, n) for p, n in spec["faults"].items()),
        snapshots=_snapshots(random.Random(seed * 100 + 99)),
        scoreboard=spec["rows"],
        fault_status=TAG,
        brain_status=TAG,
        source=SOURCE,
    )
    return dict(export_dashboard(data))


ACTS = {"freedoom": (FREEDOOM, 1), "coding": (CODING, 2)}


def render(act: str) -> str:
    spec, seed = ACTS[act]
    return json.dumps(build(act, spec, seed), separators=(",", ":")) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for act in ACTS:
        (OUT / f"{act}.json").write_text(render(act))


if __name__ == "__main__":
    main()
