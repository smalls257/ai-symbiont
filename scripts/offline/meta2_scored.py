"""META2's scored step: pinned settings, then every registered row once on held-out repos.

`pin` turns the exploratory run into the settings file a prereg pins: per row its chosen setting,
its validation thresholds per wiring seed and the sha256 of each start it loads. `score` refuses
to run without a frozen prereg and the pinned settings sha, only then builds held-out labels, and
counts every row at its fixed thresholds: nothing is chosen on the held-out repositories.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import meta2_inputs as md
import meta2_jobs as mj
import torch

PREREG_NAME = "2026-10-28-meta2.md"
# sha256 of results/meta2-settings.json as committed with the prereg draft.
SETTINGS_SHA256 = "267f2ae1e7cf6520313683992484e3362a25a090c48eba6abb933a59c53ca688"
SEEDS = (0, 1, 2)


def file_sha(path: Path) -> str:
    """sha256 of one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start_files(name: str, chosen: dict[str, Any], starts: Path) -> dict[str, Path]:
    """The MAML and broad checkpoint files a network's chosen rows load, by key."""
    lr = chosen["maml_lr_and_outer_step"][0]
    files = {f"maml seed {s}": starts / f"maml-{name}-{s}-{lr:g}.pt" for s in SEEDS}
    files.update({f"broad seed {s}": starts / f"broad-{name}-{s}.pt" for s in SEEDS})
    return files


def pin(explore: dict[str, Any], starts: Path) -> dict[str, Any]:
    """The settings document: chosen settings, thresholds per row and seed, start shas."""
    networks = {}
    for name in md.NETWORKS:
        chosen = {k: v for k, v in explore["settings"][name].items() if k != "curves_early_value"}
        files = start_files(name, chosen, starts)
        networks[name] = {**chosen, "start_sha256": {k: file_sha(p) for k, p in files.items()}}
    return {
        "run_label": "exploratory",
        "asks": "META2 settings and thresholds fixed on the validation repositories",
        "code_commit": explore["code_commit"],
        "chosen_on": "validation repositories, early-window value at the primary price",
        "networks": networks,
        "thresholds": explore["thresholds"],
    }


def settings_sha(path: Path, *, enforce: bool) -> str:
    """sha256 of the settings file; a scored run raises unless it is the pinned one."""
    found = file_sha(path)
    if enforce and found != SETTINGS_SHA256:
        raise SystemExit(f"{path}: sha256 {found} is not the pinned {SETTINGS_SHA256!r}")
    return found


def loaded(path: Path, sha: str) -> list:
    """A checkpoint list, refused if its bytes are not the pinned ones."""
    if file_sha(path) != sha:
        raise SystemExit(f"{path}: sha256 differs from the settings file")
    return torch.load(path)


def fixed_rows(name: str, seed: int, pinned: dict[str, Any], starts: Path) -> dict[str, Any]:
    """Every registered row of one network and wiring seed, at its pinned setting."""
    net, key = mj.net_of(name, seed), (name, seed)
    sha = pinned["start_sha256"]
    lr, step = pinned["maml_lr_and_outer_step"]
    maml = dict(loaded(starts / f"maml-{name}-{seed}-{lr:g}.pt", sha[f"maml seed {seed}"]))
    broad = dict(loaded(starts / f"broad-{name}-{seed}.pt", sha[f"broad seed {seed}"]))
    rows = mj.broad_rows(net, broad[pinned["broad_epochs"]], key)
    return {
        "cold": mj.online_on_scoring(net, net.cold_params(), key),
        "MAML start": mj.online_on_scoring(net, maml[step], key),
        "broad": rows["frozen"],
        "broad + fine-tune": rows[f"fine-tune {pinned['fine_tune_steps']}"],
        "in-domain": rows["in-domain"],
    }


def thresholds(pinned: dict[str, Any], row: str) -> dict[int, tuple[float, float]]:
    """One row's validation thresholds per seed; None was a tier that never speaks."""
    inf = float("inf")
    return {
        int(s): (inf if at[0] is None else at[0], inf if at[1] is None else at[1])
        for s, at in pinned["thresholds"][row].items()
    }


def load_settings(path: Path) -> dict[str, Any]:
    """The pinned settings document."""
    return json.loads(path.read_text())


def scored_job(job: tuple) -> tuple[tuple, dict[str, Any]]:
    """One forked job of the scored run: a network seed's rows, or the classifier rows."""
    if job[0] == "logistic":
        return job, mj.logistic_job()
    _, name, seed, settings, starts = job
    return job[:3], fixed_rows(name, seed, settings["networks"][name], Path(starts))


def scored_rows(scorer: Any, found: dict, counters: dict, settings: dict) -> dict[str, Any]:
    """Every registered row counted at its pinned validation thresholds."""
    logistic = found[("logistic",)]
    single = {
        "counters": counters,
        "logistic own tasks": logistic["own"],
        "logistic broad": logistic["broad"],
        "logistic broad + refit": logistic["refit"],
    }
    rows = {r: scorer.counted({0: risks}, thresholds(settings, r)) for r, risks in single.items()}
    for name in md.NETWORKS:
        per_seed = {job[2]: res for job, res in found.items() if job[:2] == ("fixed", name)}
        for row in ("cold", "MAML start", "broad", "broad + fine-tune", "in-domain"):
            label = f"{name} {row}"
            risks = {seed: res[row] for seed, res in per_seed.items()}
            rows[label] = scorer.counted(risks, thresholds(settings, label))
    return rows
