"""Paired traced games: the same map, seed and skill played under many different cards.

Spark plays every case with each card at 32 decisions (the depth check showed 16 is too few for a
lesson to matter). Every decision, situation and outcome stays in the episode logs; the pairs
within a case are the best-versus-worst material for mining Spark's own situational lessons.
Selection levels only (never validation, never held out). Resumable.

Usage: paired_traces.py --root DIR --wad WAD --state RUN3_STATE --levels FILE [--workers N]
"""

import argparse
import json
import sys
from pathlib import Path

import script_paths

script_paths.add_script_dirs()

import card_sensitivity  # noqa: E402 - needs the sibling path added above
import frozen_cards  # noqa: E402
import play_case  # noqa: E402
import run_evolve  # noqa: E402
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.card_genome import Card, Lesson  # noqa: E402
from symbiont.act1.evolve_split import TRAINING_SKILLS, EvolveSplit  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort, SparkApiError, SparkReplyError  # noqa: E402

RUN = "traces-32"
DECISIONS = 32  # the depth check: 4 of 12 exits at 32, none at 16, nothing more at 48
SEEDS_PER_MAP = 6
SEED_BASE = 940_001  # far from every earlier block (generations 911k to 914k, sensitivity 700k)
RUN_CAP = 6.0  # dollars: about 340 games of up to 32 decisions at about 0.012 a game
CARD_IDS_FROM_RUN3 = (
    "c1fcde8132f3",
    "da1852",
    "95b3bb",
)  # id prefixes: the ones that led a generation
ONE_MOVE = Card.of(
    [
        Lesson(
            "Sending several moves in one reply",
            "Send exactly one move per reply and read what happened before the next one",
            "Does your reply hold more than one line? Cut it to the single best move.",
        )
    ]
)


def trace_cases(split: EvolveSplit) -> list[Case]:
    """Selection levels times fresh seeds, skills cycling through the training skills."""
    cases = []
    for level_number, level in enumerate(split.selection):
        for index in range(SEEDS_PER_MAP):
            skill = TRAINING_SKILLS[(level_number + index) % len(TRAINING_SKILLS)]
            seed = SEED_BASE + level_number * SEEDS_PER_MAP + index
            cases.append(Case(level, seed, skill, CutSetting.NONE))
    return cases


def run3_cards(state_path: Path) -> list[Card]:
    """The run 3 cards (both arms) whose ids start with one of CARD_IDS_FROM_RUN3."""
    found: dict[str, Card] = {}
    for path in (state_path, state_path.parent.parent / "duel3-control" / "state.json"):
        for generation in json.loads(path.read_text())["generations"].values():
            for lessons in generation["cards"]:
                card = Card.from_json(lessons)
                found[card.card_id] = card
    chosen = [c for i, c in found.items() if i.startswith(CARD_IDS_FROM_RUN3)]
    if len(chosen) != len(CARD_IDS_FROM_RUN3):
        raise KeyError(f"expected {len(CARD_IDS_FROM_RUN3)} run 3 cards, found {len(chosen)}")
    return chosen


def varied_cards(args: argparse.Namespace) -> list[Card]:
    """Empty, the fixed mined and hand-written cards, a bad one, one move per reply, run 3's."""
    base = [
        Card.of([]),
        frozen_cards.MINED_CARD,
        card_sensitivity.STRONG_CARD,
        card_sensitivity.BAD_CARD,
        ONE_MOVE,
    ]
    return base + run3_cards(args.state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--levels", type=Path, default=Path("results/evolve-levels.json"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(argv)
    split = EvolveSplit.of(run_evolve.read_smoke(args.levels))
    store = run_state.RunStore(args.root / RUN)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"low; current; {DECISIONS} decisions; varied cards",
        }  # fmt: skip
    )
    replies = spark_players.SparkPlayers(
        run=RUN, run_cap=RUN_CAP, effort=Effort.LOW, max_tokens=DEFAULT_MAX_TOKENS
    )
    setup = play_case.EngineSetup(
        wad=args.wad,
        episodes=args.root / RUN / "episodes",
        decisions=DECISIONS,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
    )
    player = run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)
    pairs = [(card, case) for case in trace_cases(split) for card in varied_cards(args)]
    done: list[GameResult] = []
    player.play_many(pairs, lambda _card, _case, result: done.append(result))
    print(f"{len(done)} games", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
