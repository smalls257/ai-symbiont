"""Plain-Glimmer screen of the constructed demo trap tasks (never a benchmark result).

run_calibration.run_once's agent, settings and grading, but in the row's own `image` (a ready
/testbed, no prepare_script), so the running calibration's shared IMAGE is never touched. Records
append to <out_dir>/traps.jsonl, trajectories to <out_dir>/traj (never committed).

Usage: python screen_traps.py <rows.json> <out_dir> [--runs 2] [--reasoning low] [--step-limit 50]
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models.litellm_model import LitellmModel
from run_calibration import (
    Setting,
    _new_record,
    _run_agent,
    agent_config,
    glimmer_url,
    token_counts,
)
from taskenv import TaskEnvError, grade

STAGE = "trap-screen"
WORKERS = 2  # the Glimmer server has 2 slots
AGENT_COMMAND_TIMEOUT_S = 60  # as run_calibration: the slow-suite trap is built around it


def open_task_environment(image: str) -> DockerEnvironment:
    """The agent's container: the task image as is, no network, same env as calibration."""
    return DockerEnvironment(
        image=image,
        cwd="/testbed",
        timeout=AGENT_COMMAND_TIMEOUT_S,
        env={
            "PAGER": "cat",
            "MANPAGER": "cat",
            "PIP_PROGRESS_BAR": "off",
            "TQDM_DISABLE": "1",
            "BASH_ENV": "/root/.bashrc",
        },
        interpreter=["bash", "-c"],
        run_args=["--rm", "--network", "none"],
    )


def attempt(row: dict, setting: Setting, traj: Path, rec: dict) -> str | None:
    """Run the agent on one task; record its outcome and return the submitted patch."""
    agent_cfg, model_cfg = agent_config(setting)
    env = None
    patch = None
    try:
        env = open_task_environment(row["image"])
        agent = DefaultAgent(LitellmModel(**model_cfg), env, output_path=traj, **agent_cfg)
        info = _run_agent(agent, row, rec)
        rec |= {"exit_status": info.get("exit_status"), "steps": agent.n_calls}
        rec |= token_counts(agent.messages)
        patch = info.get("submission") or ""
        rec |= {"submitted": bool(patch.strip()), "patch_lines": len(patch.splitlines())}
    except Exception as error:  # noqa: BLE001  one run's failure is recorded, never raised
        rec["error_kind"], rec["error"] = "infra", f"{type(error).__name__}: {str(error)[-500:]}"
        rec["traceback_tail"] = traceback.format_exc()[-800:]
    finally:
        if env is not None:
            env.cleanup()
    return patch


def grade_into(rec: dict, row: dict, patch: str) -> None:
    """Grade the submitted patch in a fresh container of the task image."""
    try:
        graded = grade(row["image"], row, patch, prepare=False)
        rec |= {
            "resolved": graded.resolved,
            "patch_applied": graded.patch_applied,
            "f2p": [graded.f2p_passed, graded.f2p_total],
            "p2p": [graded.p2p_passed, graded.p2p_total],
        }
    except TaskEnvError as error:
        rec["error_kind"] = "infra"
        rec["error"] = (rec["error"] or "") + f" | grade: {str(error)[-500:]}"


def screen_once(row: dict, run: int, setting: Setting, out_dir: Path) -> dict:
    """One plain-Glimmer run on one trap task; `resolved` is None when grading could not happen."""
    rec = _new_record(row, run, setting, STAGE) | {"image": row["image"], "label": row["label"]}
    started = time.time()
    traj = out_dir / "traj" / row["instance_id"] / f"run{run}-{setting.reasoning}.traj.json"
    patch = attempt(row, setting, traj, rec)
    if patch is not None and rec["error_kind"] != "model_api":
        grade_into(rec, row, patch)
    rec.setdefault("resolved", None)
    rec["wall_s"] = round(time.time() - started, 1)
    return rec


def parse_args() -> argparse.Namespace:
    """Command line: rows, output folder, runs per task and the run setting."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--reasoning", default="low")
    parser.add_argument("--step-limit", type=int, default=50)
    parser.add_argument("--wall-limit-min", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    """Run every task `--runs` times, two at a time, appending one record per run."""
    args = parse_args()
    glimmer_url()  # a missing endpoint stops here, before any container starts
    setting = Setting(args.reasoning, args.step_limit, args.wall_limit_min * 60)
    rows = json.loads(args.rows.read_text())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    log, lock = args.out_dir / "traps.jsonl", threading.Lock()

    def one(job: tuple[dict, int]) -> None:
        rec = screen_once(job[0], job[1], setting, args.out_dir)
        with lock, log.open("a") as out:
            out.write(json.dumps(rec) + "\n")
        print(rec["instance_id"], rec["run"], rec.get("resolved"), rec.get("steps"), flush=True)

    jobs = [(row, run) for run in range(1, args.runs + 1) for row in rows]
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, jobs))


if __name__ == "__main__":
    main()
