"""The scored card test: refuses to start unless everything the prereg promised is true.

`check` is the gate and `run --scored` plays the games. The prereg must be frozen and committed
alone, its pinned code must be HEAD's, both cards must match their hashes, and every case must be
on one of the seven named held-out maps. A refusal is raised, never labeled.

Usage: final_test.py check|run --prereg PATH [--scored --wad WAD --root DIR]
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import frozen_cards  # noqa: E402 - needs the sibling path added above
import score_final  # noqa: E402

from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.levels import LevelSplit, split_of  # noqa: E402
from symbiont.eval.prereg_git import require_frozen  # noqa: E402

PINNED_PATHS = ("scripts/evolve", "src")
PIN = re.compile(r"Code pinned at ([0-9a-f]{40})")
CARD_BLOCK = re.compile(
    r"(?P<name>Mined card|Strong hand-written card)[^\n]*sha256 `(?P<sha>[0-9a-f]{64})`[^\n]*\n"
    r"\s*```\n(?P<text>.*?)\n```",
    re.DOTALL,
)
RESULTS_SCHEMA = "evolve-card-v1"
SPEND_CAP = 2.0  # dollars for this run's ledger name; the planned spend is 1.5 plus replays
MAX_REPLAYS = 3  # an ungraded game is replayed at most this many times
DROP_LIMIT = 0.10  # more than this share of cases dropped: the run is incomplete, never scored
Git = Callable[[Sequence[str]], str]


class ScoredRefusalError(RuntimeError):
    """The scored test was asked for on something the prereg does not describe."""


class IncompleteRunError(RuntimeError):
    """Too many cases were dropped: the result is reported as incomplete, never scored."""


@dataclass(frozen=True)
class CheckReport:
    """What the check verified, recorded in the results file."""

    code_commit: str
    freeze_commit: str
    pinned_commit: str
    prereg_sha256: str
    card_hashes: dict[str, str]


def git_in(root: Path) -> Git:
    """A git runner for one repository."""

    def run(args: Sequence[str]) -> str:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise ScoredRefusalError(f"git {' '.join(args)} failed: {done.stderr.strip()[:200]}")
        return done.stdout.strip()

    return run


def require_cards(text: str) -> dict[str, str]:
    """Both cards' quoted text and sha256 in the prereg equal what the code computes."""
    found = {m["name"]: (m["sha"], m["text"]) for m in CARD_BLOCK.finditer(text)}
    wanted = {
        "Mined card": frozen_cards.MINED_CARD,
        "Strong hand-written card": frozen_cards.STRONG_CARD,
    }
    hashes = {}
    for name, card in wanted.items():
        if name not in found:
            raise ScoredRefusalError(
                f"the prereg does not quote the {name.lower()} with its sha256"
            )
        quoted_hash, quoted_text = found[name]
        actual = frozen_cards.card_sha256(card)
        if quoted_hash != actual or quoted_text != card.render():
            raise ScoredRefusalError(
                f"{name}: the code's card does not match the prereg's text or hash"
            )
        hashes[name] = actual
    return hashes


def require_levels(cases: Sequence[Case]) -> None:
    """Every case is on one of the seven named held-out maps, and no (map, seed) repeats."""
    seen: set[tuple[str, int]] = set()
    for case in cases:
        if (
            case.level not in frozen_cards.HELD_OUT_MAPS
            or split_of(case.level) != LevelSplit.HELD_OUT
        ):
            raise ScoredRefusalError(f"{case.level} is not one of the seven named held-out maps")
        if (case.level, case.seed) in seen:
            raise ScoredRefusalError(f"{case.level} seed {case.seed} appears twice")
        seen.add((case.level, case.seed))


def require_pinned_code(prereg: Path, text: str, git: Git, root: Path) -> tuple[str, str, str]:
    """The freeze commit touched only the prereg, its parent is the pin, the code equals the pin."""
    relative = str(prereg.resolve().relative_to(root.resolve()))
    freeze = git(["log", "-1", "--format=%H", "--", relative])
    changed = git(["diff-tree", "--no-commit-id", "--name-only", "-r", freeze]).splitlines()
    if changed != [relative]:
        raise ScoredRefusalError(f"the freeze commit {freeze[:10]} changed more than {relative}")
    pin = PIN.search(text)
    if pin is None:
        raise ScoredRefusalError("the prereg header carries no 'Code pinned at <sha>'")
    pinned = pin.group(1)
    if git(["rev-parse", f"{freeze}^"]) != pinned:
        raise ScoredRefusalError("the pinned commit is not the freeze commit's parent")
    for path in PINNED_PATHS:
        if git(["rev-parse", f"HEAD:{path}"]) != git(["rev-parse", f"{pinned}:{path}"]):
            raise ScoredRefusalError(f"{path} at HEAD differs from the pinned commit")
    if git(["status", "--porcelain", "--untracked-files=all", "--", *PINNED_PATHS]):
        raise ScoredRefusalError("scripts/evolve or src has uncommitted or untracked changes")
    return freeze, pinned, git(["rev-parse", "HEAD"])


def check(prereg: Path, root: Path, git: Git | None = None) -> CheckReport:
    """Everything the prereg promised, verified; a refusal is raised."""
    git = git or git_in(root)
    frozen = require_frozen(prereg)
    text = prereg.read_text()
    hashes = require_cards(text)
    require_levels(frozen_cards.scored_cases())
    freeze, pinned, head = require_pinned_code(prereg, text, git, root)
    return CheckReport(head, freeze, pinned, frozen.sha256, hashes)


def drop_incomplete(
    scores: dict[str, dict[Case, GameResult]], cases: Sequence[Case]
) -> tuple[list[Case], list[Case]]:
    """Cases graded in every arm, and the dropped ones; dropped from all arms or none."""
    kept, dropped = [], []
    for case in cases:
        graded = all(case in arm and arm[case].grade == Grade.GRADED for arm in scores.values())
        (kept if graded else dropped).append(case)
    if len(dropped) > DROP_LIMIT * len(cases):
        raise IncompleteRunError(f"{len(dropped)} of {len(cases)} cases dropped: result incomplete")
    return kept, dropped


def results_document(
    report: CheckReport,
    scores: dict[str, dict[Case, GameResult]],
    cases: Sequence[Case],
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Counts, ids, labels and intervals only: never card text."""
    kept, dropped = drop_incomplete(scores, cases)
    fitness_by_arm = {arm: {case: fitness(scores[arm][case]) for case in kept} for arm in scores}
    analysis = score_final.analyze(fitness_by_arm)
    roles = {"none": "floor", "mined": "under_test", "strong": "reference"}
    rows = [
        {"label": f"{arm} card" if arm != "none" else "no card", "role": roles[arm],
         "mean_fitness": sum(v.values()) / len(v)}
        for arm, v in fitness_by_arm.items()
    ]  # fmt: skip
    return {
        "schema": RESULTS_SCHEMA,
        "label": "scored card test on held-out maps [measured]",
        **asdict(report),
        "cases_planned": len(cases),
        "cases_scored": len(kept),
        "cases_dropped": len(dropped),
        "rows": rows,
        **analysis,
        **extra,
    }


def play_scored(
    player: Any, cases: Sequence[Case], batch_cases: int
) -> dict[str, dict[Case, GameResult]]:
    """Play case by case with the arms interleaved; replay an ungraded game up to MAX_REPLAYS times.

    Each batch holds whole cases in case-major, arm-minor order, so a model change in the middle
    of the run falls on all three arms of a case alike.
    """
    by_card = {card.card_id: arm for arm, card in frozen_cards.ARMS.items()}
    scores: dict[str, dict[Case, GameResult]] = {arm: {} for arm in frozen_cards.ARMS}

    def keep(card: Any, case: Case, result: GameResult) -> None:
        scores[by_card[card.card_id]][case] = result

    for start in range(0, len(cases), batch_cases):
        pairs = [
            (card, case)
            for case in cases[start : start + batch_cases]
            for card in frozen_cards.ARMS.values()
        ]
        for _ in range(1 + MAX_REPLAYS):
            player.play_many(pairs, keep)
            pairs = [
                (c, k) for c, k in pairs if scores[by_card[c.card_id]][k].grade != Grade.GRADED
            ]
            if not pairs:
                break
    return scores


def game_dates(events: Path) -> dict[str, str]:
    """The UTC dates of the first and last game, from the run's event log."""
    from datetime import UTC, datetime

    stamps = [
        json.loads(line)["at"]
        for line in events.read_text().splitlines()
        if json.loads(line)["event"] == "game"
    ]
    day = lambda at: datetime.fromtimestamp(at, UTC).date().isoformat()  # noqa: E731 - tiny helper
    return {"first_game_date": day(min(stamps)), "last_game_date": day(max(stamps))}


def run_scored(args: argparse.Namespace, report: CheckReport) -> dict[str, Any]:
    """Play all cases under the prereg's condition and score them."""
    import play_case
    import run_state
    import spark_players

    from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError

    frozen = require_frozen(args.prereg)
    directory = args.root / "card-test"
    store = run_state.RunStore(directory)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": "low, temperature 0",
        }  # fmt: skip
    )
    replies = spark_players.SparkPlayers(
        run="card-test", run_cap=SPEND_CAP, effort=Effort.LOW, temperature=0.0
    )
    setup = play_case.EngineSetup(
        wad=args.wad,
        episodes=directory / "episodes",
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
        mode=play_case.RunMode.FINAL_TEST,
        frozen_prereg=frozen,
        final_levels=frozenset(frozen_cards.HELD_OUT_MAPS),
    )
    player = run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)
    cases = frozen_cards.scored_cases()
    scores = play_scored(player, cases, args.batch_cases)
    snapshot = run_state.RunLedger("card-test").snapshot()
    extra = {"model": spark_players.MODEL, "spend": snapshot, **game_dates(store.events_path)}
    return results_document(report, scores, cases, extra)


def main(argv: list[str] | None = None) -> int:
    """check, or run --scored."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--scored", action="store_true")
    parser.add_argument("--wad", type=Path)
    parser.add_argument("--root", type=Path, default=Path.home() / "symbiont-runs" / "evolve")
    parser.add_argument("--out", type=Path, default=Path("results/evolve-card.json"))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-cases", type=int, default=4)
    args = parser.parse_args(argv)
    report = check(args.prereg, Path.cwd())
    print(json.dumps(asdict(report), indent=1))
    if args.command == "check":
        return 0
    if not args.scored or args.wad is None:
        raise ScoredRefusalError("run needs --scored and --wad")
    document = run_scored(args, report)
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(document["sentence"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
