"""Route A on a real run, offline: every step through the service's /observe, one replay file.

A thin client like the mini-SWE wrapper: each classifier entry is that call's event-log line and
each note the memory model's line; Glimmer never saw them (the run was recorded first). A refused
call, a missing event or a step count off the trajectory raises; nothing is filled in.
Usage: uv run python scripts/routea/build_routea_replay.py --trajectory ... (see replay.sh)
"""

import argparse
import copy
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_pilot_replay import (  # noqa: E402  (sibling module, found through the path line above)
    NOT_SOLVED,
    SOLVED,
    TrajectoryError,
    check_against_grader,
    steps_from_trajectory,
    totals_of,
)

from symbiont.core.memory_note import LABELS, SEPARATOR  # noqa: E402
from symbiont.core.note_rules import step_trouble  # noqa: E402
from symbiont.core.notes import happened  # noqa: E402
from symbiont.core.warner import LOOKS_ROUTINE, NOT_A_PAUSE  # noqa: E402
from symbiont.delivery.hooks import HookEvent  # noqa: E402
from symbiont.delivery.recall import (  # noqa: E402
    ServiceOfflineError,
    ServiceRefusedError,
    ServiceReplyError,
    call_service,
)
from symbiont.readers.mini_swe_agent import HARNESS, read_local_run  # noqa: E402
from symbiont.records.schema import Kind, Record  # noqa: E402

PROJECT = "sqlglot"
# demo.js shows it as "Route A note (offline replay of a real run; the coding model did not
# see these notes)"; the short value keeps the schema enum a label.
NOTE_SOURCE = "Route A offline replay"
SOURCE_LINE = "one real plain Glimmer run replayed offline through Route A; Glimmer saw no notes"
REPLAY_LABEL = "Route A replay of the same run"
REPLAY_SUBTITLE = "Same run offline: classifier and Llama 3.2 1B notes, unseen by Glimmer"
PLAIN_SUBTITLE = "Glimmer, no adapter, no notes (the recorded run)"
STEP_KINDS = (Kind.COMMAND, Kind.EDIT)
# The page's note parts are labels (dashboard/AGENTS.md, QG-SEC-04): 12 words, 120 characters.
MAX_PART_WORDS = 12
MAX_PART_CHARS = 120
CLIPPED = "[...]"  # the miner's own mark for a cut quote


class ReplayError(RuntimeError):
    """The replay cannot be shown as what the service decided; the message names the step."""


def observe_body(record: Record) -> dict[str, Any]:
    """The /observe request for one reader record, as a harness hook would send it."""
    event = (
        HookEvent.USER_PROMPT_SUBMIT if record.kind is Kind.USER_TURN else HookEvent.POST_TOOL_USE
    )
    return {
        "harness": HARNESS,
        "session_id": record.session_id,
        "event": event.value,
        "payload": {"record": asdict(record)},
    }


def bounded(text: str) -> str:
    """A note part as a page label: cut at the word and character caps, marked with [...]."""
    words = text.split()
    if len(words) > MAX_PART_WORDS:
        text = " ".join(words[: MAX_PART_WORDS - 1]) + " " + CLIPPED
    if len(text) > MAX_PART_CHARS:
        text = text[: MAX_PART_CHARS - len(CLIPPED) - 1].rstrip() + " " + CLIPPED
    return text


def note_entry(line: str) -> dict[str, str]:
    """The page note for one memory-model line; raises ReplayError when it is not three parts."""
    parts = line.split(SEPARATOR)
    if len(parts) != len(LABELS) or not all(
        p.startswith(label) for p, label in zip(parts, LABELS, strict=True)
    ):
        raise ReplayError("the service sent a note that is not one three-part line")
    what, resolved, check = (p.removeprefix(label) for p, label in zip(parts, LABELS, strict=True))
    return {
        "what": bounded(what),
        "resolved": bounded(resolved),
        "check": bounded(check.strip("`")),
        "source": NOTE_SOURCE,
    }


def classifier_entry(event: dict[str, Any], prefix: Sequence[Record]) -> dict[str, str]:
    """The classifier's decision at one step, in prose, from the service's event for it."""
    trouble = step_trouble(prefix)
    pause = happened(trouble) if trouble is not None else ""
    if "memory_model" in event:
        return _decision("speak", f"Trouble likely ahead, so a note goes out: {pause}.")
    if "held" in event:
        return _decision("stay quiet", f"Looks like trouble, but held by the note rule: {pause}.")
    if event.get("reason_none") == LOOKS_ROUTINE:
        return _decision("stay quiet", f"A pause, but it looks routine: {pause}.")
    if event.get("reason_none") == NOT_A_PAUSE:
        return _decision("stay quiet", "Not a pause a hook can speak at.")
    raise ReplayError(f"an event the replay cannot read as a decision: keys {sorted(event)}")


def _decision(speak: str, reason: str) -> dict[str, str]:
    """One classifier entry; the reason is a page label (12 words), so a long command is cut."""
    return {"who": "logistic classifier", "speak": speak, "reason": bounded(reason)}


def _event_lines(events: Path) -> list[dict[str, Any]]:
    if not events.exists():
        return []
    return [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]


def observe_all(records: Sequence[Record], port: int, events: Path) -> list[dict[str, Any]]:
    """Post every record in order; returns each call's reply and event, refusing any gap."""
    seen = len(_event_lines(events))
    replies = [call_service("/observe", observe_body(record), port) for record in records]
    logged = _event_lines(events)[seen:]
    if len(logged) != len(records):
        raise ReplayError(f"{len(records)} calls but {len(logged)} new events in {events}")
    failed = [e for e in logged if "status" in e]
    if failed:
        raise ReplayError(f"the service refused {len(failed)} calls: {failed[0]['reason']}")
    return [{"reply": r, "event": e} for r, e in zip(replies, logged, strict=True)]


def decide_steps(
    steps: list[dict[str, Any]], records: Sequence[Record], calls: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The run's steps with each step's classifier decision and note added."""
    at_steps = [i for i, r in enumerate(records) if r.kind in STEP_KINDS]
    if len(at_steps) != len(steps):
        raise ReplayError(f"{len(at_steps)} command records but {len(steps)} trajectory steps")
    decided = copy.deepcopy(steps)
    for step, index in zip(decided, at_steps, strict=True):
        call = calls[index]
        step["classifier"] = classifier_entry(call["event"], records[: index + 1])
        notes = call["reply"].get("notes", [])
        if len(notes) > 1:
            raise ReplayError(f"step {step['step']}: {len(notes)} notes; option A sends one")
        step["note"] = note_entry(notes[0]) if notes else None
    return decided


def note_costs(records: Sequence[Record], calls: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each delivered note: its step, its full line and the memory model's milliseconds."""
    at_steps = [i for i, r in enumerate(records) if r.kind in STEP_KINDS]
    costs = []
    for step, index in enumerate(at_steps, start=1):
        event, reply = calls[index]["event"], calls[index]["reply"]
        if "memory_model" in event:
            line = reply["notes"][0]
            costs.append({"step": step, "line": line, **event["memory_model"]})
    return costs


def _run(run_id: str, label: str, subtitle: str, role: str, steps: list[Any]) -> dict[str, Any]:
    return {"id": run_id, "label": label, "subtitle": subtitle, "role": role, "status": "measured",
            "model": "Glimmer", "adapter": None, "steps": steps}  # fmt: skip


def replay_document(
    task: dict[str, str], record: dict[str, int], plain: list[Any], decided: list[Any]
) -> dict[str, Any]:
    """The demo-replay-v1 file: the recorded run, then the same run with Route A's decisions."""
    result = SOLVED if plain[-1]["outcome"] == "solved" else NOT_SOLVED
    runs = [
        _run("plain", "Plain Glimmer", PLAIN_SUBTITLE, "floor", plain),
        _run("personal", REPLAY_LABEL, REPLAY_SUBTITLE, "under test", decided),
    ]
    for run in runs:
        run.update(record, totals=totals_of(run["steps"], result))
    return {"schema": "demo-replay-v1", "status": "measured", "source": SOURCE_LINE,
            "task": task, "runs": runs}  # fmt: skip


def graded_record(rows: Sequence[dict[str, Any]], task: str, run: int) -> tuple[dict, dict]:
    """The grader's row for the replayed run and the arm's record on the task."""
    mine = [r for r in rows if r["instance_id"] == task]
    shown = next((r for r in mine if r["run"] == run), None)
    if shown is None:
        raise ReplayError(f"no grader row for {task} run {run}")
    solved = sum(bool(r["resolved"]) for r in mine)
    return shown, {"shown_run": run, "runs_solved": solved, "runs_total": len(mine)}


def build(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The replay document and the delivered notes' costs."""
    rows = [json.loads(line) for line in args.grades.read_text(encoding="utf-8").splitlines()]
    grade, record = graded_record(rows, args.task, args.run)
    result = SOLVED if grade["resolved"] else NOT_SOLVED
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    plain = steps_from_trajectory(trajectory, args.task, result)
    check_against_grader(plain, grade, args.task)
    records = list(read_local_run(args.rows, PROJECT))
    calls = observe_all(records, args.port, args.events)
    repo, number = args.task.replace("__", "/").rsplit("-", 1)
    task = {"id": f"{repo.split('/')[1]}-{number}", "repo": repo, "label": args.label}
    decided = decide_steps(plain, records, calls)
    return replay_document(task, record, plain, decided), note_costs(records, calls)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("--trajectory", "--rows", "--grades", "--events", "--out", "--summary"):
        parser.add_argument(name, type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--label", required=True, help="the task's public title, a short label")
    parser.add_argument("--port", type=int, required=True)
    return parser


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        document, costs = build(args)
    except (
        ReplayError,
        TrajectoryError,
        ServiceOfflineError,
        ServiceRefusedError,
        ServiceReplyError,
    ) as refused:
        print(f"build_routea_replay: {refused}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    spoke = sum(s["classifier"]["speak"] == "speak" for s in document["runs"][1]["steps"])
    summary = {"steps": len(document["runs"][1]["steps"]), "spoke": spoke, "notes": costs}
    args.summary.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"spoke": spoke, "note_ms": [c["ms"] for c in costs]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
