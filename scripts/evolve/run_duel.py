"""Evolve run 2 on Muse Spark: noise replay, two arms, a paired final test and a report.

Players use the sensitivity check's setting B (reasoning low, temperature 0); the author and
judge use medium reasoning. Held-out maps are never played.

Usage: run_duel.py --phase noise|evolve|final|report --root DIR --wad WAD --state S --best-card ID
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
# Dollar caps by run name (the ledger counts the author's and the judge's calls in the arm's run);
# together they stay under the 3 dollar stop for this run.
CAPS = {"noise": 0.30, "evolved": 0.60, "control": 0.60, "final": 0.80}
ARM_FOR = {"evolved": Arm.EVOLVED, "control": Arm.NO_SELECTION}
SCHEMA = "evolve-run2-v1"


class NoPlayer:
    """Raises if asked to play: reading a finished phase's games must never start a new one."""

    def play(self, card: Card, case: Any) -> Any:
        """Always refuses."""
        raise RuntimeError("this phase has no stored game for that card and case")


def player_for(name: str, directory: Path, args: argparse.Namespace) -> run_state.ResumingPlayer:
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
        run=f"duel-{name}",
        run_cap=CAPS[name],
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


def phase_noise(args: argparse.Namespace) -> None:
    """Five replays of the start card on five cases: 25 games."""
    split, start = context(args)
    cases = duel.noise_cases(split, args.seed)
    players = [
        player_for("noise", args.root / f"duel-noise-r{rep}", args)
        for rep in range(1, duel.NOISE_REPLICATES + 1)
    ]
    stats = duel_phases.run_noise(start, cases, players)
    (args.root / "duel-noise.json").write_text(json.dumps(stats, indent=1))
    print("noise", json.dumps(stats))


def phase_evolve(args: argparse.Namespace) -> None:
    """One arm: five generations of two cards on five fresh cases each."""
    split, start = context(args)
    name = args.arm
    directory = args.root / f"duel-{name}"
    player = player_for(name, directory, args)
    first = run_state.ResumingPlayer(NoPlayer(), run_state.RunStore(args.root / "duel-noise-r1"))
    cases = duel.noise_cases(split, args.seed)
    start_games = [first.play(start, case) for case in cases]
    session = spark_players.RetryingSession(spark_players.spark_session(f"duel-{name}", CAPS[name]))
    setup = duel_phases.ArmSetup(
        ARM_FOR[name], split, args.seed, player,
        spark_author.SparkAuthor(session, MUTATION_EFFORT),
        spark_judge.SparkJudge(session, MUTATION_EFFORT),
        player.store,
    )  # fmt: skip
    run = duel_phases.ArmRunner(setup).go(start, start_games)
    if run.final is None:
        raise RuntimeError("the arm ended without a card")
    document = {
        "rows": run.rows,
        "final": run.final.to_json(),
        "final_id": run.final.card_id,
        "births": [birth_to_json(b) for b in run.births],
    }
    (args.root / f"duel-{name}.json").write_text(json.dumps(document, indent=1))
    print(name, json.dumps(run.rows))


def phase_final(args: argparse.Namespace) -> None:
    """Gen-0 best, control best and evolved best on the same 24 fresh cases."""
    split, start = context(args)
    cards = {"gen0": start}
    for label, name in (("evolved", "evolved"), ("control", "control")):
        stored = json.loads((args.root / f"duel-{name}.json").read_text())
        cards[label] = Card.from_json(stored["final"])
    selection, held_back = duel.final_cases(split, args.seed)
    player = player_for("final", args.root / "duel-final", args)
    scores = duel_phases.run_final(cards, selection, held_back, player)
    table = duel_phases.paired_table(scores, held_back, args.seed)
    means = {name: sum(v.values()) / len(v) for name, v in scores.items()}
    document = {
        "ids": {name: card.card_id for name, card in cards.items()},
        "means": means,
        "games": {name: len(v) for name, v in scores.items()},
        "table": table,
    }
    (args.root / "duel-final.json").write_text(json.dumps(document, indent=1))
    print("final", json.dumps(means))


def phase_report(args: argparse.Namespace) -> None:
    """Assemble the report from the phase files and the spend ledger; write it to --out."""
    from symbiont.egress.spend import Ledger

    read = lambda name: json.loads((args.root / name).read_text())  # noqa: E731 - one-line reader
    ledger = Ledger()
    runs = ("duel-noise", "duel-evolved", "duel-control", "duel-final")
    rows = [row for row in ledger.entries() if row["run"] in runs]
    spend = {
        "calls": len(rows),
        "failed_calls": sum("error" in row for row in rows),
        "dollars": round(sum(row["cost_usd"] for row in rows), 4),
        "source": "spend ledger file, the four duel runs",
    }
    arms = {"evolved": read("duel-evolved.json"), "control": read("duel-control.json")}
    report = duel_phases.build_report(read("duel-noise.json"), arms, read("duel-final.json"), spend)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print("report written", spend)


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("noise", "evolve", "final", "report"), required=True)
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
    phases = {"noise": phase_noise, "evolve": phase_evolve, "final": phase_final}
    phases["report"] = phase_report
    phases[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
