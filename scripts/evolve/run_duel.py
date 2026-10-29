"""Evolve run 2 on Muse Spark: noise replay, two arms, a paired final test and a report.

Players use the sensitivity check's setting B (reasoning low, temperature 0); the author and
judge use medium reasoning. Held-out maps are never played.

Usage: run_duel.py --phase noise|evolve|random|final|report --root DIR --wad WAD --state S
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import card_sensitivity  # noqa: E402 - needs the sibling path added above
import duel_phases  # noqa: E402
import duel_random  # noqa: E402
import play_case  # noqa: E402
import run_evolve  # noqa: E402
import run_state  # noqa: E402
import spark_author  # noqa: E402
import spark_judge  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1 import duel  # noqa: E402
from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit  # noqa: E402
from symbiont.act1.lineage import Arm, birth_to_json  # noqa: E402
from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError  # noqa: E402

PLAY_EFFORT = Effort.LOW
PLAY_TEMPERATURE = 0.0
MUTATION_EFFORT = Effort.MEDIUM
# Dollar caps by plan and phase (the ledger counts the author's and the judge's calls in the arm's
# run); each plan's caps together stay under its spend budget (run 2 three dollars, run 3 four).
PLAN_CAPS = {
    "duel": {"noise": 0.30, "evolved": 0.60, "control": 0.60, "final": 0.80, "random": 0.35},
    "duel3": {"evolved": 1.20, "control": 1.20, "final": 0.80, "random": 0.60},
}
CAPS = PLAN_CAPS["duel"]
ARM_FOR = {"evolved": Arm.EVOLVED, "control": Arm.NO_SELECTION}
SCHEMA = "evolve-run2-v1"


class NoPlayer:
    """Raises if asked to play: reading a finished phase's games must never start a new one."""

    def play(self, card: Card, case: Any) -> Any:
        """Always refuses."""
        raise RuntimeError("this phase has no stored game for that card and case")


def player_for(
    name: str, directory: Path, args: argparse.Namespace, plan: duel.DuelPlan = duel.RUN2
) -> run_state.ResumingPlayer:
    """A resumable Spark player for one run name: its own state directory and ledger name."""
    store = run_state.RunStore(directory)
    store.require_identity(
        {
            "player": "spark",
            "author": "spark",
            "model": spark_players.MODEL,
            "reasoning": f"{PLAY_EFFORT.value}, temperature {PLAY_TEMPERATURE}",
        }  # fmt: skip
    )
    replies = spark_players.SparkPlayers(
        run=f"{plan.name}-{name}",
        run_cap=PLAN_CAPS[plan.name][name],
        effort=PLAY_EFFORT,
        temperature=PLAY_TEMPERATURE,
    )
    setup = play_case.EngineSetup(
        wad=args.wad,
        episodes=directory / "episodes",
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
    )
    return run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)


def context(args: argparse.Namespace) -> tuple[EvolveSplit, Card]:
    """The split of the navigable maps and the generation-0 best card."""
    split = EvolveSplit.of(run_evolve.read_smoke(args.levels))
    state = json.loads(args.state.read_text())
    return split, card_sensitivity.best_gen0_card(state, args.best_card)


def plan_of(args: argparse.Namespace) -> duel.DuelPlan:
    """The plan the command line names (run 2 unless --plan says run 3)."""
    return duel.PLANS[args.plan]


def phase_noise(args: argparse.Namespace) -> None:
    """Run 2 only: five replays of the start card on five cases, 25 games."""
    plan = plan_of(args)
    if not plan.noise_cases:
        raise SystemExit(f"plan {plan.name} has no noise phase (it reuses run 2's replay variance)")
    split, start = context(args)
    cases = duel.noise_cases(split, args.seed, plan)
    players = [
        player_for("noise", args.root / f"{plan.name}-noise-r{rep}", args, plan)
        for rep in range(1, plan.noise_replicates + 1)
    ]
    stats = duel_phases.run_noise(start, cases, players)
    (args.root / f"{plan.name}-noise.json").write_text(json.dumps(stats, indent=1))
    print("noise", json.dumps(stats))


def start_games(args: argparse.Namespace, split: EvolveSplit, start: Card) -> list[Any]:
    """The start card's stored games from run 2's first replay: what its first children read."""
    first = run_state.ResumingPlayer(NoPlayer(), run_state.RunStore(args.root / "duel-noise-r1"))
    return [first.play(start, case) for case in duel.noise_cases(split, args.seed, duel.RUN2)]


def tools_for(name: str, args: argparse.Namespace, plan: duel.DuelPlan) -> tuple[Any, Any]:
    """The author and judge on one retrying session whose ledger name is the phase's."""
    cap = PLAN_CAPS[plan.name][name]
    session = spark_players.RetryingSession(spark_players.spark_session(f"{plan.name}-{name}", cap))
    return (
        spark_author.SparkAuthor(session, MUTATION_EFFORT),
        spark_judge.SparkJudge(session, MUTATION_EFFORT),
    )


def phase_evolve(args: argparse.Namespace) -> None:
    """One arm: the plan's generations of a current card and its children on fresh cases."""
    plan = plan_of(args)
    split, start = context(args)
    name = args.arm
    player = player_for(name, args.root / f"{plan.name}-{name}", args, plan)
    author, judge = tools_for(name, args, plan)
    setup = duel_phases.ArmSetup(
        ARM_FOR[name], split, args.seed, player, author, judge, player.store, plan
    )
    run = duel_phases.ArmRunner(setup).go(start, start_games(args, split, start))
    if run.final is None:
        raise RuntimeError("the arm ended without a card")
    document = {
        "rows": run.rows,
        "final": run.final.to_json(),
        "final_id": run.final.card_id,
        "births": [birth_to_json(b) for b in run.births],
    }
    (args.root / f"{plan.name}-{name}.json").write_text(json.dumps(document, indent=1))
    print(name, json.dumps(run.rows))


def phase_random(args: argparse.Namespace) -> None:
    """Random-operator children of the selecting arm's parents, played on the same cases."""
    plan = plan_of(args)
    split, start = context(args)
    store = run_state.RunStore(args.root / f"{plan.name}-evolved")
    cards = {start.card_id: start}
    for generation in range(1, plan.generations + 1):
        stored = store.load(Arm.EVOLVED, generation)
        if stored is not None:
            cards.update({card.card_id: card for card in stored[0]})
    reader = run_state.ResumingPlayer(NoPlayer(), store)
    rows = json.loads((args.root / f"{plan.name}-evolved.json").read_text())["rows"]
    parents = {}
    for row in rows:
        parent = cards[row["current"]]
        cases = duel.generation_cases(split, row["generation"], args.seed, plan)
        parents[row["generation"]] = (
            parent,
            [reader.play(parent, case) for case in cases],
            row["current_mean"],
        )
    player = player_for("random", args.root / f"{plan.name}-random", args, plan)
    author, judge = tools_for("random", args, plan)
    setup = duel_phases.ArmSetup(
        Arm.NO_SELECTION, split, args.seed, player, author, judge, player.store, plan
    )
    result = duel_random.run_random_children(parents, setup)
    (args.root / f"{plan.name}-random.json").write_text(json.dumps({"rows": result}, indent=1))
    print("random", json.dumps(result))


def phase_final(args: argparse.Namespace) -> None:
    """Gen-0 best, control best and evolved best on the same fresh cases."""
    plan = plan_of(args)
    split, start = context(args)
    cards = {"gen0": start}
    for label in ("evolved", "control"):
        stored = json.loads((args.root / f"{plan.name}-{label}.json").read_text())
        cards[label] = Card.from_json(stored["final"])
    selection, held_back = duel.final_cases(split, args.seed, plan)
    players = {
        name: player_for("final", args.root / f"{plan.name}-final-{name}", args, plan)
        for name in cards
    }
    scores = duel_phases.run_final(cards, selection, held_back, players)
    table = duel_phases.paired_table(scores, held_back, args.seed)
    means = {name: sum(v.values()) / len(v) for name, v in scores.items()}
    document = {
        "ids": {name: card.card_id for name, card in cards.items()},
        "means": means,
        "games": {name: len(v) for name, v in scores.items()},
        "table": table,
    }
    (args.root / f"{plan.name}-final.json").write_text(json.dumps(document, indent=1))
    print("final", json.dumps(means))


def phase_report(args: argparse.Namespace) -> None:
    """Assemble the report from the phase files and the spend ledger; write it to --out."""
    from symbiont.egress.spend import Ledger

    plan = plan_of(args)
    read = lambda name: json.loads((args.root / name).read_text())  # noqa: E731 - one-line reader
    runs = [f"{plan.name}-{phase}" for phase in PLAN_CAPS[plan.name]]
    rows = [row for row in Ledger().entries() if row["run"] in runs]
    spend = {
        "calls": len(rows),
        "failed_calls": sum("error" in row for row in rows),
        "dollars": round(sum(row["cost_usd"] for row in rows), 4),
        "source": f"spend ledger file, the {plan.name} runs",
    }
    arms = {
        "evolved": read(f"{plan.name}-evolved.json"),
        "control": read(f"{plan.name}-control.json"),
    }
    if (args.root / f"{plan.name}-random.json").exists():
        arms["random"] = read(f"{plan.name}-random.json")
    noise = read("duel-noise.json")  # run 2's replay variance serves both plans
    report = duel_phases.build_report(noise, arms, read(f"{plan.name}-final.json"), spend)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print("report written", spend)


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("noise", "evolve", "random", "final", "report"), required=True
    )
    parser.add_argument("--plan", choices=sorted(duel.PLANS), default="duel")
    parser.add_argument("--arm", choices=sorted(ARM_FOR), help="for --phase evolve")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--best-card", required=True)
    parser.add_argument("--levels", type=Path, default=Path("results/evolve-levels.json"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("results/evolve-run2.json"))
    parser.add_argument("--workers", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one phase."""
    args = parse_arguments(argv)
    phases = {
        "noise": phase_noise,
        "evolve": phase_evolve,
        "random": phase_random,
        "final": phase_final,
        "report": phase_report,
    }
    phases[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
