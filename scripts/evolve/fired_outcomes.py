"""Outcomes at the decisions where a situational lesson would fire, per game (replay, no model).

A decision "would fire" when the ranker's top score for its observation reaches the cutoff,
whether or not the arm showed anything. Each logged game is replayed in the engine to tag the
mistakes of every decision and to read the route progress over the next K decisions: a lesson is
shown for one decision, so its effect should appear within a few moves and fade after.

Usage: fired_outcomes.py --root DIR --lessons FILE --wad WAD --arms none,lessons [--out FILE]
"""

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import lesson_check  # noqa: E402 - needs the sibling path added above
import lesson_players  # noqa: E402
import play_case  # noqa: E402

from symbiont.act1.episode import RunLog, load_run_log, run_episode  # noqa: E402
from symbiont.act1.game_fitness import Case, NoRouteError, remaining_route_units  # noqa: E402
from symbiont.act1.game_pains import tag_pains  # noqa: E402
from symbiont.act1.glimmer import Reply  # noqa: E402

# A lesson is shown for one decision; three decisions (about a tenth of a 32-decision game) cover
# the moves it can steer before later choices dominate (design setting, fixed before the test).
WINDOW = 3
Loader = Callable[[Path, Case], Any]


@dataclass(frozen=True)
class DecisionOutcome:
    """What happened at one decision: tagged mistakes, and the route left when it began."""

    mistakes: int
    remaining: float | None


def progress_over(
    outcomes: list[DecisionOutcome], index: int, window: int = WINDOW
) -> float | None:
    """Route units covered from the start of decision `index` to the start of `index + window`
    (the end of the game if sooner); None if either point has no route."""
    start = outcomes[index].remaining
    end_index = min(index + window, len(outcomes) - 1)
    end = outcomes[end_index].remaining
    return None if start is None or end is None else start - end


def replay_outcomes(
    log: Path, case: Case, wad: Path, loader: Loader = play_case.load_case_level
) -> list[DecisionOutcome]:
    """Replay a logged game without a model and read each decision's outcome."""
    decisions = load_run_log(log)
    game, knowledge, rooms = loader(wad, case)
    runs: list[Any] = []
    calls = [0]

    def reply(_prompt: str) -> Reply:
        calls[0] += 1
        return Reply(decisions[calls[0] - 1].reply, "stop", 0)

    try:
        game.new_episode()
        run_episode(game, reply, len(decisions), RunLog(on_move=runs.append), knowledge=knowledge)
    finally:
        game.close()
    return per_decision(runs, tag_pains(runs, rooms), len(decisions), knowledge.nav)


def per_decision(runs: list[Any], tags: list[Any], count: int, nav: Any) -> list[DecisionOutcome]:
    """Fold moves into decisions; the route left is read at each decision's first move."""
    mistakes = [0] * count
    first: dict[int, Any] = {}
    for run, found in zip(runs, tags, strict=True):
        mistakes[run.decision] += len(found)
        first.setdefault(run.decision, run)
    out = []
    for index in range(count):
        run = first.get(index)
        out.append(DecisionOutcome(mistakes[index], _remaining(nav, run) if run else None))
    return out


def _remaining(nav: Any, run: Any) -> float | None:
    try:
        return remaining_route_units(nav, run.before.position)
    except NoRouteError:
        return None


def fired_summary(
    log: Path, case: Case, args: argparse.Namespace, cutoff: float
) -> dict[str, float] | None:
    """Mean mistakes and mean route progress over the game's would-fire decisions; None if none."""
    return fired_in(log, case, (args.lessons, args.wad, cutoff), play_case.load_case_level)


def fired_in(
    log: Path, case: Case, rule: tuple[Path, Path, float], loader: Loader
) -> dict[str, float] | None:
    """The same, for a rule of (lessons file, WAD path handed to the loader, cutoff)."""
    lessons, wad, cutoff = rule
    ranker = lesson_players.ranker_from(str(lessons))
    decisions = load_run_log(log)
    fired = [i for i, d in enumerate(decisions) if max(ranker.scores(d.observation)) >= cutoff]
    if not fired:
        return None
    outcomes = replay_outcomes(log, case, wad, loader)
    progress = [got for i in fired if (got := progress_over(outcomes, i)) is not None]
    return {
        "fired": len(fired),
        "mistakes": statistics.fmean(outcomes[i].mistakes for i in fired),
        "progress": statistics.fmean(progress) if progress else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lessons", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--arms", default="none,lessons")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tag", default="lessonchk")
    parser.add_argument(
        "--cases", type=lesson_check.CaseSet, choices=list(lesson_check.CaseSet), default="check"
    )
    args = parser.parse_args(argv)
    cutoff = json.loads((args.root / f"{args.tag}-cutoff.json").read_text())["cutoff"]
    split_cases = {f"{c.level}-s{c.seed}": c for c in _cases(args)}
    found: dict[str, dict[str, Any]] = {}
    for arm in args.arms.split(","):
        card = lesson_check.arm_card(lesson_check.Arm(arm))
        for name, case in split_cases.items():
            log = args.root / f"{args.tag}-{arm}" / "episodes" / f"{card.card_id}-{name}.jsonl"
            found.setdefault(arm, {})[name] = fired_summary(log, case, args, cutoff)
    text = json.dumps(found, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


def _cases(args: argparse.Namespace) -> list[Case]:
    import run_evolve

    from symbiont.act1.evolve_split import EvolveSplit

    split = EvolveSplit.of(run_evolve.read_smoke(Path("results/evolve-levels.json")))
    return lesson_check.cases_for(args, split)


if __name__ == "__main__":
    sys.exit(main())
