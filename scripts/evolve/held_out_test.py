"""The held-out test: refuses to start unless the frozen prereg's promises hold.

Usage: held_out_test.py check|run|score --prereg PATH --lessons FILE [--root DIR --wads DIR]
"""

import argparse
import concurrent.futures
import json
import multiprocessing
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import final_test  # noqa: E402 - needs the sibling path added above
import fired_outcomes  # noqa: E402
import frozen_cards  # noqa: E402
import held_out_cases  # noqa: E402
import held_out_score  # noqa: E402
import lesson_players  # noqa: E402
import play_case  # noqa: E402
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.egress.spark import SparkApiError, SparkReplyError  # noqa: E402
from symbiont.eval.prereg_git import require_frozen  # noqa: E402

RUN = "heldout-onemove"
SPEND_CAP = 10.0  # dollars for this run's ledger name; planned spend is about 5 including replays
CARD_SHA = re.compile(r"[Oo]ne-move card sha256 `([0-9a-f]{64})`")
LESSONS_SHA = re.compile(r"[Ll]essons file sha256 `([0-9a-f]{64})`")
CUTOFF_QUOTE = re.compile(r"[Cc]utoff `([0-9.]+)`")
KEPT_FILE = Path("results/evolve-generated-maps.json")
DECLARATION = Path("prereg/2026-10-29-generated-maps.md")
FREEDOOM_DIR = Path("data/freedoom")
SCORE_WORKERS = 4


class PreregMismatchError(RuntimeError):
    """What the frozen prereg quotes differs from what the code would run."""


def quoted(pattern: re.Pattern[str], text: str, what: str) -> str:
    """The single quoted value, or a refusal naming what is missing."""
    found = pattern.search(text)
    if found is None:
        raise PreregMismatchError(f"the prereg does not quote the {what}")
    return found.group(1)


def sha256_of(path: Path) -> str:
    """Hash of a file's bytes."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(prereg: Path, root: Path, lessons: Path, wads: Path) -> final_test.CheckReport:
    """Everything the prereg promised, verified; a refusal is raised."""
    frozen = require_frozen(prereg)
    text = prereg.read_text()
    one_move = frozen_cards.card_sha256(
        held_out_cases.ARM_SETTINGS[held_out_cases.Arm.ONE_MOVE].card
    )
    if quoted(CARD_SHA, text, "one-move card sha256") != one_move:
        raise PreregMismatchError("the one-move card differs from the prereg's hash")
    if quoted(LESSONS_SHA, text, "lessons file sha256") != sha256_of(lessons):
        raise PreregMismatchError("the lessons file differs from the prereg's hash")
    if float(quoted(CUTOFF_QUOTE, text, "cutoff")) != held_out_cases.CUTOFF:
        raise PreregMismatchError("the cutoff in the code differs from the prereg's")
    maps = held_out_cases.generated_maps(root / KEPT_FILE)
    held_out_cases.require_declared_files(maps, wads, root / DECLARATION)
    freeze, pinned, head = final_test.require_pinned_code(
        prereg, text, final_test.git_in(root), root
    )
    return final_test.CheckReport(head, freeze, pinned, frozen.sha256, {"one_move": one_move})


def arm_player(
    arm: held_out_cases.Arm, lessons: Path, root: Path, frozen: Any, workers: int
) -> Any:
    """A resumable player for one arm, in its own run directory (arms share card ids)."""
    setting = held_out_cases.ARM_SETTINGS[arm]
    directory = root / f"{RUN}-{arm.value}"
    store = run_state.RunStore(directory)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"low; {held_out_cases.DECISIONS} decisions; arm {arm.value}",
        }  # fmt: skip
    )
    replies = lesson_players.LessonPlayers(
        RUN, SPEND_CAP, str(lessons), held_out_cases.CUTOFF, str(directory / "shows.jsonl"),
        setting.delivery,
    )  # fmt: skip
    engine = play_case.EngineSetup(
        wad=FREEDOOM_DIR, episodes=directory / "episodes", decisions=held_out_cases.DECISIONS,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=workers, mode=play_case.RunMode.FINAL_TEST,
        frozen_prereg=frozen, final_levels=held_out_cases.all_levels(Path.cwd() / KEPT_FILE),
        loader=held_out_cases.LevelLoader(Path.home() / "symbiont-runs/oblige/wads"),
    )  # fmt: skip
    return run_state.ResumingPlayer(play_case.EnginePlayer(replies, engine), store)


def play_until_graded(player: Any, pairs: list[tuple[Any, Case]]) -> None:
    """Play the pairs; replay an ungraded game up to MAX_REPLAYS times on the same case."""
    grades: dict[Case, Grade] = {}

    def note(_card: Any, case: Case, result: GameResult) -> None:
        grades[case] = result.grade

    for _ in range(1 + final_test.MAX_REPLAYS):
        grades.clear()
        player.play_many(pairs, note)
        pairs = [(card, case) for card, case in pairs if grades.get(case) != Grade.GRADED]
        if not pairs:
            return


def play_all(players: dict[Any, Any], cases: tuple[Case, ...], batch: int) -> None:
    """Whole-case batches, all arms in each batch, so a model change falls on every arm alike."""
    for start in range(0, len(cases), batch):
        for arm, player in players.items():
            card = held_out_cases.ARM_SETTINGS[arm].card
            play_until_graded(player, [(card, case) for case in cases[start : start + batch]])


def all_games(root: Path, arm: held_out_cases.Arm) -> dict[Case, GameResult]:
    """The stored game of every case of one arm, graded or not."""
    games = json.loads((root / f"{RUN}-{arm.value}" / "state.json").read_text())["games"]
    results = (run_state.result_from_json(drop_player(game)) for game in games.values())
    return {result.case: result for result in results}


def drop_player(game: dict[str, Any]) -> dict[str, Any]:
    """A stored game without the player block the result type does not take."""
    return {key: value for key, value in game.items() if key != "player"}


def attempt_counts(root: Path, arm: held_out_cases.Arm) -> dict[str, int]:
    """Games started and ungraded attempts (replays) for one arm, from its event log."""
    events = (root / f"{RUN}-{arm.value}" / "events.jsonl").read_text().splitlines()
    games = [json.loads(line) for line in events if json.loads(line)["event"] == "game"]
    ungraded = sum(1 for game in games if game["grade"] != Grade.GRADED.value)
    return {"attempts": len(games), "ungraded_attempts": ungraded}


def score_one(job: tuple[str, Case, str, str, float]) -> tuple[str, Case, dict[str, float] | None]:
    """Replay one logged game and read its would-fire outcome (a pool job)."""
    arm, case, log, lessons, cutoff = job
    loader = held_out_cases.LevelLoader(Path.home() / "symbiont-runs/oblige/wads")
    summary = fired_outcomes.fired_in(
        Path(log), case, (Path(lessons), FREEDOOM_DIR, cutoff), loader
    )
    return arm, case, summary


def replay_jobs(
    root: Path, lessons: Path, kept: set[Case]
) -> list[tuple[str, Case, str, str, float]]:
    """One replay per (arm, case): the logged game, the lessons file and the cutoff."""
    ordered = sorted(kept, key=lambda each: (each.level, each.seed))
    jobs = []
    for arm in held_out_cases.Arm:
        episodes = root / f"{RUN}-{arm.value}" / "episodes"
        card_id = held_out_cases.ARM_SETTINGS[arm].card.card_id
        for case in ordered:
            log = episodes / f"{card_id}-{case.level}-s{case.seed}.jsonl"
            jobs.append((arm.value, case, str(log), str(lessons), held_out_cases.CUTOFF))
    return jobs


def read_fired(jobs: list[tuple[str, Case, str, str, float]]) -> dict[Any, dict[Case, Any]]:
    """Replay every job on a small pool of fresh interpreters (one ViZDoom engine each)."""
    fired: dict[Any, dict[Case, Any]] = {arm: {} for arm in held_out_cases.Arm}
    context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(SCORE_WORKERS, mp_context=context) as pool:
        for arm_name, case, found in pool.map(score_one, jobs, chunksize=4):
            fired[held_out_cases.Arm(arm_name)][case] = (
                None if found is None else held_out_score.Fired.of(found)
            )
    return fired


def score(root: Path, lessons: Path) -> dict[str, Any]:
    """Drop incomplete cases (refusing above 10%), replay for fires, then score both claims.

    Raises final_test.IncompleteRunError when more than 10% of the planned cases are dropped.
    """
    planned = held_out_cases.all_cases(Path.cwd() / KEPT_FILE)
    games = {arm: all_games(root, arm) for arm in held_out_cases.Arm}
    by_name = {arm.value: games[arm] for arm in games}
    kept, dropped = final_test.drop_incomplete(by_name, planned)
    fired = read_fired(replay_jobs(root, lessons, set(kept)))
    fits = {arm: {c: fitness(games[arm][c]) for c in kept} for arm in games}
    return {
        "cases_planned": len(planned), "cases_scored": len(kept), "cases_dropped": len(dropped),
        "attempts_by_arm": {a.value: attempt_counts(root, a) for a in held_out_cases.Arm},
        **held_out_score.analyze(set(kept), fits, fired),
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """check, run --scored, or score."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run", "score"))
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--lessons", type=Path, required=True)
    parser.add_argument("--scored", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.home() / "symbiont-runs" / "evolve")
    parser.add_argument("--wads", type=Path, default=Path.home() / "symbiont-runs/oblige/wads")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-cases", type=int, default=8)
    parser.add_argument("--out", type=Path, default=Path("results/evolve-onemove.json"))
    args = parser.parse_args(argv)
    report = check(args.prereg, Path.cwd(), args.lessons, args.wads)
    print(json.dumps(asdict(report), indent=1))
    if args.command == "check":
        return 0
    if args.command == "run":
        if not args.scored:
            raise final_test.ScoredRefusalError("run needs --scored")
        players = {
            a: arm_player(a, args.lessons, args.root, args.workers) for a in held_out_cases.Arm
        }
        play_all(players, held_out_cases.all_cases(Path.cwd() / KEPT_FILE), args.batch_cases)
        return 0
    import vizdoom

    document = {
        "schema": "evolve-onemove-v1", "vizdoom_version": vizdoom.__version__,
        **asdict(report), **score(args.root, args.lessons),
    }  # fmt: skip
    args.out.write_text(json.dumps(document, indent=1, default=str) + "\n")
    print(document["result"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
