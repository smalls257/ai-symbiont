"""Export one level and seed, played by two arms, as a demo-replay-v1 file for the demo page.

Reads the records and decision logs collect_episodes.py wrote. The plain arm is the floor and has
no adapter; the personal arm names its adapter. Labels say what really played: a scripted
stand-in pair is labeled as such through --model, and the page shows that label.

Usage: uv run python scripts/act1/export_demo_replay.py --episodes DIR --level MAP03 --seed 2
  --adapter freedoom --out FILE [--plain P] [--personal Q] [--model M] [--status measured]
"""

import argparse
import json
from pathlib import Path

from symbiont.act1.demo_replay import ArmEpisode, ReplayTask, demo_replay
from symbiont.act1.episode import load_run_log
from symbiont.records.schema import load_jsonl

GLIMMER = "Muse Glimmer 30B (Q4_K_M), reasoning low"


def arm_episode(args: argparse.Namespace, arm: str, policy: str, adapter: str | None) -> ArmEpisode:
    """One arm's files; raises FileNotFoundError naming the missing one."""
    stem = args.episodes / args.level / f"{args.level}-{policy}-s{args.seed}"
    with Path(f"{stem}.jsonl").open(encoding="utf-8") as handle:
        records = list(load_jsonl(handle))
    decisions = load_run_log(Path(f"{stem}.decisions.jsonl"))
    return ArmEpisode(arm, policy, args.model, adapter, decisions, records)


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--plain", default="glimmer_plain", help="policy name of the floor arm")
    parser.add_argument("--personal", default="glimmer_personal")
    parser.add_argument("--adapter", required=True, help="the personal arm's adapter name")
    parser.add_argument("--model", default=GLIMMER, help="what played; say so for a stand-in")
    parser.add_argument("--status", default="measured")
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_arguments(argv)
    plain = arm_episode(args, "plain", args.plain, None)
    personal = arm_episode(args, "personal", args.personal, args.adapter)
    source = f"act1 episodes {args.level} seed {args.seed}: {args.plain} vs {args.personal}"
    document = demo_replay(ReplayTask(args.level, args.seed, source, args.status), plain, personal)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    totals = {run["id"]: run["totals"] for run in document["runs"]}
    print(json.dumps({"out": str(args.out), "totals": totals}, indent=1))


if __name__ == "__main__":
    main()
