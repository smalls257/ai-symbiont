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

from symbiont.eval import meta2_report as rep

PREREG_NAME = "2026-10-28-meta2.md"
# sha256 of results/meta2-settings.json as committed with the prereg draft.
SETTINGS_SHA256 = "267f2ae1e7cf6520313683992484e3362a25a090c48eba6abb933a59c53ca688"
SEEDS = (0, 1, 2)
UNDER_TEST = ("cold", "MAML start", "broad + fine-tune")  # per network: the six candidate rows
LIVE = "logistic broad"  # the live warner
REFERENCES = ("counters", "logistic own tasks", "logistic broad + refit", LIVE)
# The prereg's tie order for the slot, plainest first (rule 6).
SLOT_ORDER = tuple(f"{name} {row}" for name in (md.DENSE, md.FLY) for row in UNDER_TEST)
EARLY = "first 10 tasks"


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


def word(differences: dict, first: str, second: str) -> dict[str, Any]:
    """The early-window paired difference `first minus second` and its word."""
    return differences[f"{first} minus {second}"][EARLY]


def line(name: str, found: dict[str, Any]) -> str:
    """A verdict's first line: the word, then the interval."""
    return (
        f"{name}: {found['standing']} {found['value']:.3f} "
        f"[{found['ci95_low']:.3f}, {found['ci95_high']:.3f}]"
    )


def eligible(differences: dict, early: dict, row: str) -> bool:
    """Rule 6: earns, beats counters, and is not worse than the live warner."""
    return (
        early[row]["ci95_low"] > 0
        and word(differences, row, "counters")["standing"] == "better"
        and word(differences, row, LIVE)["standing"] != "worse"
    )


def best_of(rows: list[str], early: dict) -> str | None:
    """Highest early point estimate, ties to the plainest (rule 6 order)."""
    if not rows:
        return None
    return max(rows, key=lambda row: (round(early[row]["value"], 12), -SLOT_ORDER.index(row)))


def compare_networks(fly: str, dense: str, scorer: Any, rows: dict) -> dict[str, Any]:
    """Rule 6's one comparison: best fly row minus best DenseNet row; a tie stays with the fly."""
    window = rep.Window.EARLY
    compared = rep.difference(
        rows[fly]["windows"][window], rows[dense]["windows"][window], scorer.option
    )
    words = {"tie": "not distinguishable at this size", "better": "better", "worse": "better"}
    winner = md.DENSE if compared["standing"] == "worse" else md.FLY
    return {"slot": winner, "words": words[compared["standing"]], "fly_minus_dense": compared}


def slot(differences: dict, early: dict, scorer: Any, rows: dict) -> dict[str, Any]:
    """Rule 6: which network fills the slot, from eligible rows only."""
    ok = [r for r in SLOT_ORDER if eligible(differences, early, r)]
    fly = best_of([r for r in ok if r.startswith(md.FLY)], early)
    dense = best_of([r for r in ok if r.startswith(md.DENSE)], early)
    if fly is None and dense is None:
        found = {"slot": "empty", "words": "counters or the classifier are the warner at this size"}
    elif fly is None or dense is None:
        only = md.FLY if dense is None else md.DENSE
        found = {"slot": only, "words": "the only eligible network"}
    else:
        found = compare_networks(fly, dense, scorer, rows)
    return {"eligible": ok, **found}


def verdicts(differences: dict, early: dict, scorer: Any, rows: dict) -> dict[str, Any]:
    """H1 to H5, the slot and the "meta learner works" claim, by the frozen rules."""
    found = {
        "H1 fly MAML start minus fly cold": word(
            differences, f"{md.FLY} MAML start", f"{md.FLY} cold"
        ),
        "H2 DenseNet MAML start minus DenseNet cold": word(
            differences, f"{md.DENSE} MAML start", f"{md.DENSE} cold"
        ),
    }
    for name in md.NETWORKS:
        found[f"H3 {name} broad + fine-tune minus broad"] = word(
            differences, f"{name} broad + fine-tune", f"{name} broad"
        )
        found[f"H4 {name} MAML start minus counters"] = word(
            differences, f"{name} MAML start", "counters"
        )
    beats = [r for r in SLOT_ORDER if word(differences, r, LIVE)["standing"] == "better"]
    fly_maml = f"{md.FLY} MAML start"
    works = (
        found["H1 fly MAML start minus fly cold"]["standing"] == "better"
        and word(differences, fly_maml, "counters")["standing"] == "better"
        and word(differences, fly_maml, LIVE)["standing"] != "worse"
    )
    claim = (
        "the meta learner works"
        if works
        else ("a meta-learned start did not measurably help on new issues at this size")
    )
    lines = [line(k, v) for k, v in found.items()]
    lines.append(
        f"H5 no under-test row beats the live warner: {'holds' if not beats else 'fails'} {beats}"
    )
    return {
        "table": [*lines, f"claim: {claim}"],
        "words": found,
        "H5_rows_better_than_live_warner": beats,
        "slot": slot(differences, early, scorer, rows),
        "result": claim,  # a label field of the results-content gate
    }
