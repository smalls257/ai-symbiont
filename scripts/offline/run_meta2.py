"""META2: does a network get better on a repository's NEW issues after its earlier ones?

One trajectory per task in issue order; learn from tasks 1..k, score task k+1; option A value
over the first 10 tasks and after. Counters and the classifier sit beside each network cold,
from a MAML start, broad, broad plus fine-tune, and in-domain. `explore` reads validation only.
Usage: OMP_NUM_THREADS=1 run_meta2.py {explore|pin|score} ... (see --help of each step)
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import meta2_episodes as me
import meta2_inputs as md
import meta2_jobs as mj
import meta2_scored as sc
import meta2_select as ms
import run_penalized as t36
import run_selection as g6

from symbiont.eval import meta2_report as rep
from symbiont.eval.note_cost_report import NET
from symbiont.eval.prereg_git import run_provenance

log = logging.getLogger("meta2")
CHECK_REPOS = 3  # validation repositories the torch-equals-numpy check replays


def interval(scorer: ms.Scorer, counted: dict[str, Any]) -> dict[str, Any]:
    """Net value per 100 steps [95% CI] and the secondary rates, per window."""
    return {w.value: rep.value_of(counted["windows"][w], scorer.option) for w in rep.Window}


def thresholds_of(counted: dict[str, Any]) -> dict[str, list[float | None]]:
    """seed -> [note, warning], None for a tier that never speaks."""
    return {
        str(s): [None if t == float("inf") else t for t in at]
        for s, at in counted["thresholds"].items()
    }


def paired(scorer: ms.Scorer, rows: dict[str, Any], pairs: list[tuple[str, str]]) -> dict:
    """Each named difference per window, on the same draws."""
    return {
        f"{a} minus {b}": {
            w.value: rep.difference(rows[a]["windows"][w], rows[b]["windows"][w], scorer.option)
            for w in rep.Window
        }
        for a, b in pairs
    }


def named_pairs() -> list[tuple[str, str]]:
    """What each technique is compared with."""
    pairs = []
    for name in md.NETWORKS:
        pairs += [
            (f"{name} MAML start", f"{name} cold"),
            (f"{name} broad + fine-tune", f"{name} broad"),
        ]
        for row in ("cold", "MAML start", "broad + fine-tune"):
            pairs += [
                (f"{name} {row}", ref)
                for ref in ("counters", "logistic own tasks", "logistic broad + refit")
            ]
    return pairs


def shares(scorer: ms.Scorer, rows: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """Share of the in-domain gain the fine-tune recovers, per network and window."""
    found = {}
    for name in md.NETWORKS:
        value = {
            k: {w: rep.net(rows[f"{name} {k}"]["windows"][w], scorer.option) for w in rep.Window}
            for k in ("broad", "broad + fine-tune", "in-domain")
        }
        found[name] = {
            w.value: rep.share_recovered(
                value["broad + fine-tune"][w], value["broad"][w], value["in-domain"][w]
            )
            for w in rep.Window
        }
    return found


def table_lines(rows: dict[str, Any]) -> list[str]:
    """One line per row: early and late value with intervals."""
    lines = []
    for name, by_window in rows.items():
        cells = [
            f"{by_window[w.value][NET]['value']:.3f} [{by_window[w.value][NET]['ci95_low']:.3f}, "
            f"{by_window[w.value][NET]['ci95_high']:.3f}]"
            for w in (rep.Window.EARLY, rep.Window.LATE)
        ]
        lines.append(f"{name} | {cells[0]} | {cells[1]}")
    return lines


def assemble(scorer: ms.Scorer, found: dict, counters: dict) -> dict[str, Any]:
    """Rows, settings, differences and shares on the validation repositories."""
    rows = ms.reference_rows(scorer, found, counters)
    settings = {}
    for name in md.NETWORKS:
        block = ms.network_rows(scorer, found, name)
        rows.update(block["rows"])
        settings[name] = block["settings"]
    values = {name: interval(scorer, counted) for name, counted in rows.items()}
    return {
        "floors": ms.floor_rows(scorer, counters),
        "rows": values,
        "thresholds": {name: thresholds_of(c) for name, c in rows.items()},
        "settings": settings,
        "differences": paired(scorer, rows, named_pairs()),
        "share_of_in_domain_gain_recovered": shares(scorer, rows),
        "table": table_lines(values),
        "logistic_own_silent_tasks": found[("logistic",)]["own_silent_tasks"],
    }


def explore(args: argparse.Namespace) -> None:
    """Every job on the validation repositories, then selection and the table."""
    started, episodes = time.time(), Path(args.episodes)
    train, _ = md.load_role(episodes / "train.npz")
    valid, counters = md.load_role(episodes / "validation.npz")
    mj.prepare(train, valid, Path(args.starts))
    gaps = {name: mj.torch_matches_numpy(name, sorted(valid)[:CHECK_REPOS]) for name in md.NETWORKS}
    log.info("torch rule steps equal the numpy rules: %s", gaps)
    found = dict(g6.pool_map(mj.run_job, mj.all_jobs(), args.workers))
    body = assemble(ms.Scorer(valid), found, counters)
    for line in body["table"]:
        log.info(line)
    document = {
        "run_label": "exploratory",
        "asks": "META2: value on new issues after a repository's earlier tasks (validation only)",
        "code_commit": t36.git_head(),
        "repos": {"train": len(train), "validation": sorted(valid)},
        "tasks": {
            "train": sum(len(r.task_ids) for r in train.values()),
            "validation": sum(len(r.task_ids) for r in valid.values()),
        },
        "torch_equals_numpy_max_gap": gaps,
        **body,
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


def report_body(scorer: ms.Scorer, rows: dict[str, Any], counters: dict) -> dict[str, Any]:
    """Rows, differences, shares and the table, the same for the scored run as for explore."""
    values = {name: interval(scorer, counted) for name, counted in rows.items()}
    return {
        "floors": ms.floor_rows(scorer, counters),
        "rows": values,
        "differences": paired(scorer, rows, named_pairs()),
        "share_of_in_domain_gain_recovered": shares(scorer, rows),
        "table": table_lines(values),
    }


def pin(args: argparse.Namespace) -> None:
    """The settings file a prereg pins, from the exploratory run and its saved starts."""
    explore_doc = json.loads(Path(args.explore).read_text())
    Path(args.out).write_text(json.dumps(sc.pin(explore_doc, Path(args.starts)), indent=1))
    log.info("wrote %s (sha256 %s)", args.out, sc.file_sha(Path(args.out)))


def held_out_episodes(args: argparse.Namespace) -> tuple[dict, dict]:
    """Held-out labels, built only after the prereg and settings checks have passed."""
    build = argparse.Namespace(
        data_dir=args.data_dir, out=args.episodes, roles=["held_out"], workers=args.workers
    )
    me.build(build)
    return md.load_role(Path(args.episodes) / "held_out.npz")


def score(args: argparse.Namespace) -> None:
    """The scored run: guards first, then held-out labels, rows at pinned thresholds, report."""
    started = time.time()
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=sc.PREREG_NAME)
    sha = sc.settings_sha(Path(args.settings), enforce=args.scored)
    settings = sc.load_settings(Path(args.settings))
    train, _ = md.load_role(Path(args.episodes) / "train.npz")
    held, counters = held_out_episodes(args)
    mj.prepare(train, held, Path(args.starts))
    gaps = {name: mj.torch_matches_numpy(name, sorted(held)[:CHECK_REPOS]) for name in md.NETWORKS}
    jobs: list[tuple] = [
        ("fixed", name, seed, settings, args.starts) for name in md.NETWORKS for seed in (0, 1, 2)
    ]
    found = dict(g6.pool_map(sc.scored_job, [*jobs, ("logistic",)], args.workers))
    scorer = ms.Scorer(held)
    body = report_body(scorer, sc.scored_rows(scorer, found, counters, settings), counters)
    for line in body["table"]:
        log.info(line)
    document = {
        **label,
        "code_commit": t36.git_head(),
        "settings_sha256": sha,
        "repos": sorted(held),
        "tasks": {r: len(held[r].task_ids) for r in sorted(held)},
        "torch_equals_numpy_max_gap": gaps,
        **body,
        "logistic_own_silent_tasks": found[("logistic",)]["own_silent_tasks"],
        "wall_clock_s": time.time() - started,
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


def parser_of() -> argparse.ArgumentParser:
    """The three steps and their arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="step", required=True)
    steps = {
        "explore": ("episodes", "starts", "out"),
        "pin": ("explore", "starts", "out"),
        "score": ("episodes", "data-dir", "starts", "settings", "out"),
    }
    for step, names in steps.items():
        one = sub.add_parser(step)
        for name in names:
            one.add_argument(f"--{name}", required=True)
        one.add_argument("--workers", type=int, default=10)
    sub.choices["score"].add_argument("--scored", action="store_true")
    sub.choices["score"].add_argument("--prereg")
    return parser


def main() -> None:
    """Parse the command line and run one step."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    args = parser_of().parse_args()
    {"explore": explore, "pin": pin, "score": score}[args.step](args)


if __name__ == "__main__":
    main()
