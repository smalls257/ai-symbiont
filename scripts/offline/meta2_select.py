"""META2 selection and tables on the validation repositories (exploratory).

Every candidate gets its own (note, warning) pair per wiring seed, chosen on all validation
tasks by the T46 rule; settings (MAML step size and stopping point, broad epochs, fine-tune
budget) are then chosen by early-window VALUE, never by loss, ties to the setting nearest the
cold or broad start. The table puts counters and the classifier rows beside every network row.
"""

from collections.abc import Mapping
from typing import Any

import meta2_jobs as mj
import numpy as np

from symbiont.eval import meta2_report as rep
from symbiont.eval.confirm_report import floor_counts
from symbiont.eval.meta2_replay import RepoTasks
from symbiont.eval.note_cost_report import NET, scored

SEEDS = (0, 1, 2)
Candidate = Mapping[int, Mapping[str, list[np.ndarray]]]  # seed -> repository -> task risks


class Scorer:
    """Thresholds and window counts of candidates on fixed repositories, at the primary price."""

    def __init__(self, repos: Mapping[str, RepoTasks]) -> None:
        """The repositories every candidate is scored on."""
        self.repos, self.option = repos, rep.primary_option()

    def traces(self, risks: Candidate) -> dict[int, dict[str, rep.Traces]]:
        """seed -> repository -> one trace per task."""
        return {
            s: {r: rep.task_traces(self.repos[r], by_repo[r]) for r in self.repos}
            for s, by_repo in risks.items()
        }

    def counted(self, risks: Candidate) -> dict[str, Any]:
        """Thresholds per seed and the scored counts of every window."""
        traces = self.traces(risks)
        at = {s: rep.choose_thresholds(t, self.option) for s, t in traces.items()}
        windows = {w: rep.window_counts(traces, at, w, self.option) for w in rep.Window}
        return {"thresholds": at, "windows": windows}

    def early(self, counted: Mapping[str, Any]) -> float:
        """Early-window net value per 100 steps: the selection metric."""
        return rep.net(counted["windows"][rep.Window.EARLY], self.option)


def best(scorer: Scorer, candidates: Mapping[Any, Candidate]) -> tuple[Any, dict, dict]:
    """The candidate with the highest early value; ties to the first listed (nearest start)."""
    counted = {key: scorer.counted(risks) for key, risks in candidates.items()}
    curve = {str(key): scorer.early(c) for key, c in counted.items()}
    chosen = max(
        counted, key=lambda key: (round(scorer.early(counted[key]), 12), -list(counted).index(key))
    )
    return chosen, counted[chosen], curve


def by_seed(found: Mapping[tuple, Any], kind: str, name: str) -> dict[int, Any]:
    """seed -> one job's result for (kind, network)."""
    return {job[2]: result for job, result in found.items() if job[0] == kind and job[1] == name}


def maml_candidates(found: Mapping[tuple, Any], name: str) -> dict[tuple, Candidate]:
    """(step size, outer step) -> seed -> risks; outer step 0 is the cold start."""
    runs = {j: r for j, r in found.items() if j[0] == "maml" and j[1] == name}
    steps = sorted(next(iter(runs.values()))["risks"])
    return {
        (lr, step): {j[2]: r["risks"][step] for j, r in runs.items() if j[3] == lr}
        for step in steps
        for lr in mj.MAML_LRS
    }


def broad_choice(scorer: Scorer, found: Mapping[tuple, Any], name: str) -> dict[str, Any]:
    """Broad epochs by the frozen row's value, then the fine-tune budget at those epochs."""
    broad = by_seed(found, "broad", name)
    epochs = {e: {s: broad[s]["risks"][e]["frozen"] for s in SEEDS} for e in mj.BROAD_EPOCHS}
    epoch, broad_counted, epoch_curve = best(scorer, epochs)
    at_epoch = {s: broad[s]["risks"][epoch] for s in SEEDS}
    tunes = {n: {s: at_epoch[s][f"fine-tune {n}"] for s in SEEDS} for n in mj.FINE_TUNE_STEPS}
    budget, tune_counted, tune_curve = best(scorer, tunes)
    return {
        "rows": {
            "broad": broad_counted,
            "broad + fine-tune": tune_counted,
            "in-domain": scorer.counted({s: at_epoch[s]["in-domain"] for s in SEEDS}),
        },
        "settings": {"broad_epochs": epoch, "fine_tune_steps": budget},
        "curves": {"broad": epoch_curve, "fine_tune": tune_curve},
    }


def network_rows(scorer: Scorer, found: Mapping[tuple, Any], name: str) -> dict[str, Any]:
    """Cold, MAML, broad, broad plus fine-tune and the in-domain ceiling of one network."""
    cold = {s: r["risks"] for s, r in by_seed(found, "cold", name).items()}
    maml_key, maml_counted, maml_curve = best(scorer, maml_candidates(found, name))
    broad = broad_choice(scorer, found, name)
    rows = {f"{name} cold": scorer.counted(cold), f"{name} MAML start": maml_counted}
    rows.update({f"{name} {row}": counted for row, counted in broad["rows"].items()})
    settings = {
        "maml_lr_and_outer_step": list(maml_key),
        **broad["settings"],
        "curves_early_value": {"maml": maml_curve, **broad["curves"]},
    }
    return {"rows": rows, "settings": settings}


def reference_rows(scorer: Scorer, found: Mapping[tuple, Any], counters: Mapping) -> dict:
    """Counters and the classifier rows (one seed: they have no wiring)."""
    logistic = found[("logistic",)]
    return {
        "counters": scorer.counted({0: counters}),
        "logistic own tasks": scorer.counted({0: logistic["own"]}),
        "logistic broad": scorer.counted({0: logistic["broad"]}),
        "logistic broad + refit": scorer.counted({0: logistic["refit"]}),
    }


def floor_rows(scorer: Scorer, counters: Mapping) -> dict[str, dict[str, Any]]:
    """Warn never and a note at every allowed step, per window."""
    traces = scorer.traces({0: counters})[0]
    found: dict[str, dict[str, Any]] = {}
    for window in rep.Window:
        windowed = {r: rep.in_window(t, window) for r, t in traces.items()}
        lay = rep.window_counts({0: traces}, {0: (np.inf, np.inf)}, window, scorer.option).layout
        for floor, counts in floor_counts(windowed, scorer.option, lay).items():
            found.setdefault(floor, {})[window.value] = scored(
                counts, scorer.option.value, lay.draws
            )[NET]
    return found
