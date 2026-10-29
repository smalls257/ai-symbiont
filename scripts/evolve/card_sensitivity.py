"""Card-sensitivity check: does any setting make a card change how Spark plays?

Four cards (empty, best generation 0, a bad one, a strong one) play the same twelve fresh cases
under four settings: A current, B temperature 0, C medium reasoning, D card as system rules.

Usage: card_sensitivity.py --root DIR --wad WAD --state STATE --best-card ID --out FILE [--only A,B]
"""

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import play_case  # noqa: E402 - needs the sibling path added above
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.card_genome import Card, Lesson  # noqa: E402
from symbiont.act1.card_prompt import CardPlacement  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting  # noqa: E402
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort, SparkApiError, SparkReplyError  # noqa: E402

LEVELS = ("MAP01", "MAP05")
# Fresh seeds: none of them was played in any evolution generation, validation or final test.
SEEDS = tuple(range(700_001, 700_007))
# Two-sided 5% test at 80% power: games per card = 2 * (1.96 + 0.84)^2 * (sd / gap)^2.
GAMES_FACTOR = 2 * (1.96 + 0.84) ** 2
SCHEMA = "evolve-sensitivity-v1"
# At medium reasoning 8 of 48 games ended ungraded because the default 4096 tokens ran out while
# thinking; the medium setting gets room for the thinking and the move lines.
MEDIUM_TOKENS = 16384


class Setting(StrEnum):
    """The four settings compared."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True)
class SettingSpec:
    """What a setting changes."""

    effort: Effort
    temperature: float | None
    placement: CardPlacement
    run_cap: float
    words: str
    max_tokens: int = DEFAULT_MAX_TOKENS


SPECS = {
    Setting.A: SettingSpec(Effort.LOW, None, CardPlacement.PROMPT_PREFIX, 0.30, "current"),
    Setting.B: SettingSpec(Effort.LOW, 0.0, CardPlacement.PROMPT_PREFIX, 0.30, "temperature 0"),
    Setting.C: SettingSpec(
        Effort.MEDIUM, None, CardPlacement.PROMPT_PREFIX, 0.55, "reasoning medium", MEDIUM_TOKENS
    ),
    Setting.D: SettingSpec(
        Effort.LOW, None, CardPlacement.SYSTEM_RULES, 0.30, "card as system rules"
    ),
}
ORDER = (Setting.A, Setting.B, Setting.D, Setting.C)  # the dearest setting last

BAD_CARD = Card.of(
    [
        Lesson(
            "Staying facing one way",
            "Turn around 180 degrees after every move you make",
            "Did you turn around after your last move?",
        ),
        Lesson(
            "Opening doors",
            "Never open a door; do not use open_door() and do not go through doors",
            "Is any door about to be opened? Do not.",
        ),
    ]
)
STRONG_CARD = Card.of(
    [
        Lesson(
            "Wandering without a target",
            "Go to the nearest unexplored door with go_to(door) and open it",
            "Does 'Reachable with go_to' list a door you have not used yet?",
        ),
        Lesson(
            "Walking back into rooms already checked",
            "Never re-enter a room you already checked; pick a door you have not used",
            "Have you been in this room before?",
        ),
        Lesson(
            "Missing the exit",
            "When an exit sign is in view or listed, head for it with go_to(exit) at once",
            "Does the observation list an exit?",
        ),
    ]
)


def sensitivity_cases() -> list[Case]:
    """Two levels times six fresh seeds, normal skill, no cut moves: the same for every cell."""
    return [Case(level, seed, NORMAL_SKILL, CutSetting.NONE) for level in LEVELS for seed in SEEDS]


def cell_stats(results: list[GameResult]) -> dict[str, Any]:
    """Mean, SD and counts of the graded games in one (setting, card) cell."""
    graded = [fitness(r) for r in results if r.grade == Grade.GRADED]
    return {
        "games": len(graded),
        "ungraded": len(results) - len(graded),
        "mean": statistics.fmean(graded),
        "sd": statistics.stdev(graded) if len(graded) > 1 else 0.0,
    }


def games_needed(sd: float, gap: float) -> int | None:
    """Games per card to separate two cards `gap` apart at within-card SD `sd`; None: no gap."""
    return math.ceil(GAMES_FACTOR * (sd / gap) ** 2) if gap else None


def setting_report(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per-card stats, the pooled SD and the gaps against the empty card in SD units."""
    pooled = math.sqrt(statistics.fmean(c["sd"] ** 2 for c in cells.values()))
    gaps = {}
    for name in ("best_gen0", "bad", "strong"):
        gap = cells[name]["mean"] - cells["empty"]["mean"]
        gaps[name] = {
            "gap": gap,
            "gap_in_sd": gap / pooled if pooled else 0.0,
            "games_per_card_needed": games_needed(pooled, gap),
        }
    return {"cards": cells, "pooled_sd": pooled, "gaps": gaps}


def best_gen0_card(state: dict[str, Any], card_id: str) -> Card:
    """The stored generation-0 card with this id."""
    for item in state["seed_cards"]:
        card = Card.from_json(item)
        if card.card_id == card_id:
            return card
    raise KeyError(f"no seed card {card_id} in the run's state")


def players_for(setting: Setting) -> spark_players.SparkPlayers:
    """The reply factory of one setting, every field named so none can land in another's place."""
    spec = SPECS[setting]
    return spark_players.SparkPlayers(
        run=f"sens-{setting.value}",
        run_cap=spec.run_cap,
        effort=spec.effort,
        temperature=spec.temperature,
        max_tokens=spec.max_tokens,
        placement=spec.placement,
    )


def play_setting(
    setting: Setting, cards: dict[str, Card], root: Path, wad: Path, workers: int
) -> dict[str, list[GameResult]]:
    """Every card on every case under one setting; resumable, results by card name."""
    spec = SPECS[setting]
    run = f"sens-{setting.value}"
    store = run_state.RunStore(root / run)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"{spec.effort.value}; {spec.words}",
        }  # fmt: skip
    )
    replies = players_for(setting)
    engine = play_case.EngineSetup(
        wad=wad,
        episodes=root / run / "episodes",
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=workers,
        card_placement=spec.placement,
    )
    player = run_state.ResumingPlayer(play_case.EnginePlayer(replies, engine), store)
    cases = sensitivity_cases()
    found: dict[str, list[GameResult]] = {name: [] for name in cards}
    by_id = {card.card_id: name for name, card in cards.items()}

    def keep(card: Card, case: Case, result: GameResult) -> None:
        found[by_id[card.card_id]].append(result)

    player.play_many([(card, case) for card in cards.values() for case in cases], keep)
    return found


def main(argv: list[str] | None = None) -> int:
    """Run the settings (resumable) and write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="state.json holding the card")
    parser.add_argument("--best-card", required=True, help="id of the best generation-0 card")
    parser.add_argument("--only", help="comma-separated settings, default all")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(argv)
    best = best_gen0_card(json.loads(args.state.read_text()), args.best_card)
    cards = {"empty": Card.of([]), "best_gen0": best, "bad": BAD_CARD, "strong": STRONG_CARD}
    chosen = [Setting(s) for s in args.only.split(",")] if args.only else list(ORDER)
    report = {}
    for setting in [s for s in ORDER if s in chosen]:
        played = play_setting(setting, cards, args.root, args.wad, args.workers)
        report[setting.value] = setting_report({n: cell_stats(r) for n, r in played.items()})
        print(setting.value, json.dumps(report[setting.value]["gaps"]), flush=True)
    document = {
        "schema": SCHEMA,
        "label": "exploratory card-sensitivity check, Spark, 12 games per cell [measured]",
        "games_per_cell": len(sensitivity_cases()),
        "settings": report,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
