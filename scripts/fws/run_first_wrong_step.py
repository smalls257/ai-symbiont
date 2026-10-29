"""TRAIL and Who&When as first-wrong-step labels, and an exploratory check of the logistic warner.

Reads both datasets locally (read-only), labels every step (see `annotated.step_labels`), scores
the warner fitted by `scripts/routea/fit_warner.py` on them, writes the per-step labels and
risks (ids, flags and numbers, no text) to --out-dir and the counts to --results. Exploratory,
post hoc, no prereg: nothing here is a scored run, and no claim goes beyond these traces.
Usage: uv run python scripts/fws/run_first_wrong_step.py --trail ... --who-when ... \
    --weights ~/symbiont-runs/routea/warner.json --out-dir ~/symbiont-runs/fws --results ...
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "routea")]

import numpy as np  # noqa: E402  (the sibling modules need the path set above)
from annotated import AnnotatedTrace, StepLabels, TaskKind, step_labels  # noqa: E402
from tallies import agreement, around_first_wrong, label_counts, split_counts  # noqa: E402
from trail_reader import PROVENANCE as TRAIL  # noqa: E402
from trail_reader import read_trail  # noqa: E402
from warner_check import StepTable, label_scores, restricted  # noqa: E402
from who_when_reader import PROVENANCE as WHO_WHEN  # noqa: E402
from who_when_reader import read_who_when  # noqa: E402

from symbiont.core.features import featurise  # noqa: E402
from symbiont.core.slot import Situation  # noqa: E402
from symbiont.core.warner import WarnerWeights, warner_risk, weights_from  # noqa: E402
from symbiont.eval.offline import WINDOW  # noqa: E402

SCORED_LABELS = ("at_first_wrong", "first_wrong_ahead", "error_ahead", "mined_trouble_ahead")
NOTE = (
    "exploratory, post hoc: counts and labels only; TRAIL is gated on Hugging Face and both "
    "datasets stay local; risks come from the warner fitted on the public OpenHands pool"
)
RULE = (
    "first wrong step = earliest step an annotator marked wrong (TRAIL: the step holding the "
    "error span; Who&When: mistake_step); first_wrong_ahead = it lies in (t, t+5], our label shape"
)


def trace_risks(trace: AnnotatedTrace, weights: WarnerWeights) -> np.ndarray:
    """The warner's risk at every step, each from its own session prefix (empty history)."""
    records = trace.records
    return np.asarray(
        [
            warner_risk(weights, featurise(Situation(records[0].project, records[: t + 1], (), ())))
            for t in range(len(records))
        ]
    )


def step_table(traces: Sequence[AnnotatedTrace], labels: Sequence[StepLabels], risks) -> StepTable:
    """One table over every step of the traces, sessions numbered in trace order."""
    return StepTable(
        risks=np.concatenate(risks),
        boundary=np.concatenate([one.boundary for one in labels]).astype(bool),
        session=np.concatenate([np.full(len(one.boundary), n) for n, one in enumerate(labels)]),
        position=np.concatenate([np.arange(len(one.boundary)) for one in labels]),
        labels={
            name: np.concatenate([getattr(one, name) for one in labels]).astype(bool)
            for name in SCORED_LABELS
        },
    )


def up_to_first_wrong(traces: Sequence[AnnotatedTrace]) -> np.ndarray:
    """Steps at or before each trace's first wrong step: the stretch a warning could change."""
    return np.concatenate(
        [
            np.arange(len(t.records)) <= (t.first_wrong if t.first_wrong is not None else -1)
            for t in traces
        ]
    )


def warner_scores(
    traces: Sequence[AnnotatedTrace], labels, risks, weights: WarnerWeights
) -> dict[str, object]:
    """Every label scored on all steps, and the first wrong step on steps up to it."""
    table = step_table(traces, labels, risks)
    scores: dict[str, object] = {
        name: label_scores(table, name, weights.note_at) for name in SCORED_LABELS
    }
    prefix = restricted(table, up_to_first_wrong(traces))
    scores["at_first_wrong_steps_up_to_it"] = label_scores(
        prefix, "at_first_wrong", weights.note_at
    )
    return {"role": "under_test", "traces": len(traces)} | scores


def grouped(traces: Sequence[AnnotatedTrace], key) -> dict[str, list[int]]:
    """Trace indexes by a key, in first-seen order."""
    groups: dict[str, list[int]] = defaultdict(list)
    for n, trace in enumerate(traces):
        groups[key(trace)].append(n)
    return dict(groups)


def per_group(traces, labels, risks, weights, key) -> dict[str, dict[str, object]]:
    """Counts, label agreement and warner scores of every group of traces."""
    report = {}
    for name, rows in grouped(traces, key).items():
        part = [traces[n] for n in rows]
        part_labels = [labels[n] for n in rows]
        report[name] = {
            "label_counts": label_counts(part_labels),
            "mined_vs_annotated_steps": agreement(part_labels),
            "around_first_wrong": around_first_wrong(part, part_labels, WINDOW),
            "warner": warner_scores(part, part_labels, [risks[n] for n in rows], weights),
        }
    return report


def local_rows(traces, labels, risks) -> list[dict[str, object]]:
    """Per-step ids, flags and risks for the local run directory: no text."""
    rows = []
    for trace, one, risk in zip(traces, labels, risks, strict=True):
        for t, record in enumerate(trace.records):
            flags = {name: bool(getattr(one, name)[t]) for name in SCORED_LABELS}
            rows.append(
                {"session": record.session_id, "step": t, "kind": record.kind.value}
                | flags
                | {"boundary": bool(one.boundary[t]), "risk": round(float(risk[t]), 5)}
            )
    return rows


def parsed_args() -> argparse.Namespace:
    """The command line: dataset roots, the weights file and where outputs go."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--trail", "--who-when", "--weights", "--out-dir", "--results"):
        parser.add_argument(flag, type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parsed_args()
    started = time.monotonic()
    document = json.loads(args.weights.expanduser().read_text())
    weights = weights_from(document)
    trail = read_trail(args.trail.expanduser())
    for error in trail.unreadable:
        print(f"unreadable: {error.path.name} line {error.line_no}", file=sys.stderr)
    blame = read_who_when(args.who_when.expanduser())
    traces = trail.traces + [check.trace for check in blame]
    labels = [step_labels(trace) for trace in traces]
    risks = [trace_risks(trace, weights) for trace in traces]
    out = args.out_dir.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    with (out / "steps.jsonl").open("w") as fh:
        fh.writelines(json.dumps(row) + "\n" for row in local_rows(traces, labels, risks))
    result = {
        "exploratory": True,
        "post_hoc": True,
        "prereg": None,
        "note": NOTE,
        "datasets": {"trail": TRAIL.dataset, "who_and_when": WHO_WHEN.dataset},
        "label": {"rule": RULE, "window_steps": WINDOW},
        "sources": source_counts(trail, blame),
        "by_task_kind": per_group(traces, labels, risks, weights, _task_kind),
        "by_split": per_group(traces, labels, risks, weights, _split_name),
        "weights": weights_meta(document),
        "wall_clock_s": round(time.monotonic() - started, 1),
    }
    args.results.write_text(json.dumps(result, indent=1) + "\n")
    coding = result["by_task_kind"].get(TaskKind.CODING.value, {}).get("warner", {})
    print(json.dumps({k: coding.get(k) for k in ("traces", *SCORED_LABELS)}, indent=1))


def _task_kind(trace: AnnotatedTrace) -> str:
    return trace.task_kind.value


def _split_name(trace: AnnotatedTrace) -> str:
    return f"{trace.source}:{trace.split}"


def source_counts(trail, blame) -> dict[str, object]:
    """Per source and split: traces, steps, placements, unreadable files, blame checks."""
    by_split = grouped(trail.traces, lambda trace: trace.split)
    trail_counts = {
        s: split_counts([trail.traces[n] for n in rows]) for s, rows in by_split.items()
    }
    trail_counts["unreadable_files"] = len(trail.unreadable)
    trail_counts["annotations_paired_by_file_name"] = trail.paired_by_file_name
    who_splits = grouped([c.trace for c in blame], lambda trace: trace.split)
    who_counts = {
        split: split_counts([blame[n].trace for n in rows])
        | {"blamed_agent_wrote_blamed_step": sum(blame[n].agent_matches is True for n in rows)}
        for split, rows in who_splits.items()
    }
    return {"trail": trail_counts, "who_and_when": who_counts}


def weights_meta(document: dict) -> dict[str, object]:
    """Where the warner came from: its fit's own counts, no weights."""
    fit = document["fit"]
    return {
        "source": "scripts/routea/fit_warner.py on the public OpenHands pool",
        "note_at": round(float(document["note_at"]), 4),
        "out_of_fold_auc_on_pool": fit["out_of_fold_auc"],
        "precision_on_pool": fit["precision"],
        "pool_sessions": document["data"]["sessions"],
    }


if __name__ == "__main__":
    main()
