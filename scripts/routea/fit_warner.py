"""Fit Route A's logistic warner on the public OpenHands pool and write its weights file.

Grouped out-of-fold risks and option A are in `warner_fit`; a record from any other dataset, or a
held-out repository, stops the run. Every step is featurised from its own session prefix only
(empty history), exactly as `/observe` sees it. Weights go outside the repo; only counts are
printed.
Usage: uv run python scripts/routea/fit_warner.py --pool ... --out ...
"""

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from warner_fit import Steps, auc, choose_threshold, fit_logistic, out_of_fold_risks, score

from symbiont.core.features import N_FEATURES, featurise
from symbiont.core.note_rules import step_trouble
from symbiont.core.slot import Situation
from symbiont.eval.offline import WINDOW, pain_labels
from symbiont.readers.errors import ReadError
from symbiont.readers.openhands import PROVENANCE, read
from symbiont.records.schema import Record

# T46 declared these held out for scoring; sqlglot's T36 test split must not be read either.
REFUSED_REPOS = frozenset(
    {"python-pillow__Pillow", "iterative__dvc", "conan-io__conan", "tobymao__sqlglot"}
)
FOLDS = 5
FOLD_SEED = 20261029  # the T36/T46 split seed
L2_GRID = (1.0, 10.0, 100.0)


def session_columns(session: list[Record]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Features, labels and boundary marks of one session, from its own prefix only."""
    points = pain_labels(session, {}, frozenset())
    trouble_at = {point.step for point in points}
    rows, labels, marks = [], [], []
    for t in range(len(session)):
        prefix = tuple(session[: t + 1])
        rows.append(featurise(Situation(session[0].project, prefix, (), ())))
        step = session[t].step
        labels.append(any(step < s <= step + WINDOW for s in trouble_at))
        marks.append(step_trouble(prefix) is not None)
    return np.asarray(rows), np.asarray(labels), np.asarray(marks)


COLUMNS = ("features", "labels", "boundary", "session")


def repo_columns(path: Path) -> dict[str, list[np.ndarray]]:
    """Every session of one repository file as per-session columns, sessions numbered from 0."""
    by_session: dict[str, list[Record]] = defaultdict(list)
    for record in read(path, path.stem):
        if record.provenance != PROVENANCE:
            raise ValueError(f"{path.name}: a record is not from the public OpenHands dataset")
        by_session[record.session_id].append(record)
    columns: dict[str, list[np.ndarray]] = {name: [] for name in COLUMNS}
    for index, session in enumerate(by_session.values()):
        values = (*session_columns(session), np.full(len(session), index))
        for name, value in zip(COLUMNS, values, strict=True):
            columns[name].append(value)
    return columns


def load_steps(files: list[Path], workers: int) -> tuple[Steps, dict[str, int]]:
    """Steps of every readable file; a file that does not parse is named and counted."""
    folds = list(range(FOLDS)) * (len(files) // FOLDS + 1)
    random.Random(FOLD_SEED).shuffle(folds)
    parts: dict[str, list[np.ndarray]] = {name: [] for name in (*COLUMNS, "fold")}
    sessions, unreadable = 0, 0
    with ProcessPoolExecutor(workers) as pool:
        for path, fold, done in zip(files, folds, pool.map(_columns_or_error, files), strict=False):
            if isinstance(done, str):
                print(f"unreadable {path.name}: {done}", file=sys.stderr)
                unreadable += 1
                continue
            for name in ("features", "labels", "boundary"):
                parts[name] += done[name]
            parts["session"] += [ids + sessions for ids in done["session"]]
            parts["fold"] += [np.full(len(ids), fold) for ids in done["session"]]
            sessions += len(done["session"])
    stacked = [np.concatenate(parts[name]) for name in (*COLUMNS, "fold")]
    counts = {"files": len(files) - unreadable, "files_unreadable": unreadable}
    return Steps(*stacked), counts | {"sessions": sessions, "steps": len(stacked[1])}


def _columns_or_error(path: Path) -> dict[str, list[np.ndarray]] | str:
    try:
        return repo_columns(path)
    except ReadError as exc:
        return str(exc)


def pool_files(pool: Path, limit: int | None) -> list[Path]:
    """The pool's repository files in name order; refuses a held-out repository."""
    files = sorted(pool.glob("*.jsonl"))
    refused = [f.stem for f in files if f.stem in REFUSED_REPOS]
    if refused:
        raise ValueError(f"the pool holds held-out repositories: {', '.join(refused)}")
    return files[:limit] if limit else files


def fitted(steps: Steps) -> dict[str, object]:
    """Pick L2 and threshold on out-of-fold risks, then fit on every step."""
    trials = {}
    for l2 in L2_GRID:
        risks = out_of_fold_risks(steps, l2)
        trials[l2] = (choose_threshold(steps, risks), auc(steps.labels, risks))
        print(f"l2={l2:g} value={trials[l2][0].value:.1f} auc={trials[l2][1]:.3f}", file=sys.stderr)
    l2 = max(trials, key=lambda key: trials[key][0].value)
    choice, held_out_auc = trials[l2]
    final = fit_logistic(steps.features, steps.labels, l2)
    total_steps = len(steps.labels)
    return {
        "mean": final.mean.tolist(),
        "scale": final.scale.tolist(),
        "coef": final.coef.tolist(),
        "note_at": choice.note_at,
        "fit": {
            "l2": l2,
            "out_of_fold_auc": round(held_out_auc, 4),
            "notes": choice.notes,
            "right_notes": choice.right,
            "precision": round(choice.right / choice.notes, 4),
            "net_value_per_100_steps": round(100 * choice.value / total_steps, 4),
            "trouble_rate": round(float(steps.labels.mean()), 4),
            "boundary_rate": round(float(steps.boundary.mean()), 4),
            "floor_note_every_boundary": _floor(steps),
        },
    }


def _floor(steps: Steps) -> float:
    """Net value per 100 steps of a note at every allowed boundary step (risk ignored)."""
    every = score(steps, np.ones(len(steps.labels)), 0.5)
    return round(100 * every.value / len(steps.labels), 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-repos", type=int, help="first N files by name (a quick fit)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    started = time.monotonic()
    steps, counts = load_steps(pool_files(args.pool.expanduser(), args.max_repos), args.workers)
    assert steps.features.shape[1] == N_FEATURES
    document = fitted(steps)
    document["data"] = counts | {"dataset": PROVENANCE.dataset, "license": PROVENANCE.license}
    document["wall_clock_s"] = round(time.monotonic() - started, 1)
    out = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document))
    print(
        json.dumps({k: document[k] for k in ("note_at", "fit", "data", "wall_clock_s")}, indent=1)
    )


if __name__ == "__main__":
    main()
