"""Play one Freedoom game with Muse Spark and write its episode files (one process per game).

Violation prevented: Black Box on spend and Silent Fallback on API failure. The run name ties
every call to the shared ledger, so processes playing in parallel share one run cap; a failing
call stops the game with its error (the half-written decision log stays for inspection) and is
never retried into a fake move. Episodes land in the same layout as the Glimmer history, so the
lesson builder, the replay renderer and the paired summary read them unchanged.

    uv run python scripts/act1/probe_spark.py --level MAP01 --seed 1 --effort low \
        --run spark-probe-1 --run-cap 2.0 --out ~/symbiont-runs/act1learn/spark/episodes
"""

import argparse
import json
from pathlib import Path

from collect_episodes import Plan, collect_episode, load_level, wad_path

from symbiont.act1.episode_records import Episode
from symbiont.act1.levels import require_training
from symbiont.act1.policies import Policy
from symbiont.act1.spark_player import spark_reply_fn
from symbiont.egress.credentials import load_meta_key
from symbiont.egress.spark import Effort, SparkSession
from symbiont.egress.spend import Tier, caps_from_environment
from symbiont.records.schema import Provenance

MODEL = "muse-spark-1.3-contributor"
DECISIONS = 16
# Self-play episode records are Spark-safe by construction (episode_records.PROVENANCE).
PROVENANCE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--level", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--effort", choices=[effort.value for effort in Effort], required=True)
    parser.add_argument("--run", required=True, help="ledger run name shared by parallel games")
    parser.add_argument("--run-cap", type=float, required=True, help="dollars for the whole run")
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def play(args: argparse.Namespace) -> dict:
    """One game; raises on a cap, a refusal, an API error or a level that is not for training."""
    require_training(args.level)
    effort = Effort(args.effort)
    policy_name = f"spark_{effort.value}"
    session = SparkSession(
        MODEL, Tier.CONTRIBUTOR, args.run, caps_from_environment(args.run_cap), load_meta_key(),
        provenance=(PROVENANCE,),
    )  # fmt: skip
    label = f"{args.level}-s{args.seed}-{effort.value}"
    reply = spark_reply_fn(session, effort, label)

    def make_policy(name: str, _seed: int) -> Policy:
        return Policy(name, reply)

    level_setup = load_level(wad_path(), args.level)
    try:
        episode = Episode(args.level, policy_name, args.seed)
        return collect_episode(level_setup, episode, Plan(DECISIONS, make_policy), Path(args.out))
    finally:
        level_setup[0].close()


def main(argv: list[str] | None = None) -> None:
    print(json.dumps(play(parse_arguments(argv))), flush=True)


if __name__ == "__main__":
    main()
