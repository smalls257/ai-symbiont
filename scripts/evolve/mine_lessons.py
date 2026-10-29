"""Mine Spark's own situational lessons from its best and worst games on the same map and seed.

For each case of the paired traced games the best and the worst game are shown to Muse Spark,
which writes up to three lessons, each pinned to a decision of the worse game; that decision's
observation becomes the lesson's example situation. "One move per reply" joins the pool, anchored
on moments where a multi-move reply met trouble. Selection-level cases only.

Usage: mine_lessons.py --run-dir DIR --out FILE [--min-gap 0.25] [--cap 2.0]
"""

import argparse
import concurrent.futures
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import spark_players  # noqa: E402 - needs the sibling path added above

from symbiont.act1.episode import load_run_log  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.act1.steplog import Decision  # noqa: E402
from symbiont.egress.spark import Effort  # noqa: E402

RUN = "lessons-mine"
LINE = re.compile(r"^LESSON\s*\|\s*(\d+)\s*\|\s*(.+)$")
SEEN_CHARS, MOVE_CHARS = 260, 150  # what a decision shows the author, per game line
MAX_ADVICE_WORDS = 28
REPLY_TOKENS = 8192
TROUBLE = ("enemy in the way", "blocked", "no path", "stuck", "timeout", "did not", "locked")
ONE_MOVE = "Send one move per reply and read what happened before choosing the next one"
ONE_MOVE_EXAMPLES = 40


class MiningReplyError(ValueError):
    """A reply held no usable lesson line; the pair is counted as unparsed, never guessed."""


def case_of(game: dict[str, Any]) -> Case:
    """The case a stored game was played on."""
    played = game["case"]
    return Case(played["level"], played["seed"], played["skill"], CutSetting(played["cuts"]))


def fitness_of(game: dict[str, Any]) -> float:
    """A stored graded game's fitness."""
    return fitness(
        GameResult(
            case=case_of(game), card_id=game["card_id"], grade=Grade.GRADED,
            exit_reached=game["exit_reached"], route_share=game["route_share"],
            mistakes=game["mistakes"], died=game["died"], kills=game["kills"],
            cut_moves=game["cut_moves"], ungraded_reason=None,
        )
    )  # fmt: skip


def best_and_worst(run_dir: Path, min_gap: float) -> list[tuple[Path, Path, str]]:
    """Per case with a big enough gap: the best log, the worst log and the case name."""
    games = json.loads((run_dir / "state.json").read_text())["games"]
    by_case: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for key, game in games.items():
        if game["grade"] == Grade.GRADED.value:
            card, level, seed = key.split("|")[:3]
            by_case[f"{level}-s{seed}"].append((fitness_of(game), card))
    pairs = []
    for name, found in sorted(by_case.items()):
        found.sort()
        if found[-1][0] - found[0][0] >= min_gap:
            logs = [
                run_dir / "episodes" / f"{card}-{name}.jsonl" for _, card in (found[-1], found[0])
            ]
            pairs.append((logs[0], logs[1], name))
    return pairs


def game_text(decisions: list[Decision]) -> str:
    """One line per decision: what the player saw, said and got."""
    lines = []
    for d in decisions:
        said = " / ".join(x.strip() for x in d.reply.splitlines() if x.strip())
        got = "; ".join(o.removeprefix("scripted ") for o in d.outcomes)
        lines.append(
            f"[{d.index}] SEES: {d.observation[:SEEN_CHARS]} SAID: {said} GOT: {got[:MOVE_CHARS]}"
        )
    return "\n".join(lines)


def mining_prompt(better: list[Decision], worse: list[Decision]) -> str:
    """Ask for up to three lessons pinned to decisions of the worse game."""
    return (
        "Two games of the same level and start: a better one and a worse one. Each line is one "
        "decision (what the player saw, the moves it chose, what the moves did).\n\n"
        f"BETTER GAME\n{game_text(better)}\n\nWORSE GAME\n{game_text(worse)}\n\n"
        "Write up to 3 lessons the player could use in a moment like one in the worse game. Each "
        "lesson is one line in exactly this form:\n"
        f"LESSON | <decision number in the worse game where it applies> | <advice in at most "
        f"{MAX_ADVICE_WORDS} words, plain words, no numbers, no map names>\n"
        "Say nothing else."
    )


def parse_lessons(text: str, worse: list[Decision]) -> list[tuple[str, str]]:
    """(advice, situation) pairs. Raises MiningReplyError when no line is usable."""
    found = []
    for line in text.strip().splitlines():
        match = LINE.match(line.strip())
        if not match or int(match[1]) >= len(worse):
            continue
        advice = match[2].strip()
        if len(advice.split()) <= MAX_ADVICE_WORDS:
            found.append((advice, worse[int(match[1])].observation))
    if not found:
        raise MiningReplyError("the reply held no lesson line that fits the worse game")
    return found


def mine_pair(session: Any, pair: tuple[Path, Path, str]) -> list[tuple[str, str]]:
    """One Spark call for one case."""
    better, worse = load_run_log(pair[0]), load_run_log(pair[1])
    label = f"evolve/{RUN}/mine/{pair[2]}"
    reply = session.chat(mining_prompt(better, worse), Effort.LOW, label, REPLY_TOKENS)
    return parse_lessons(reply.text, worse)


def one_move_lesson(run_dir: Path) -> dict[str, Any]:
    """The multi-move-reply lesson, anchored on observations where such a reply met trouble."""
    examples: list[str] = []
    for log in sorted((run_dir / "episodes").glob("*.jsonl")):
        for d in load_run_log(log):
            multi = len([x for x in d.reply.splitlines() if x.strip()]) > 1
            if multi and any(word in " ".join(d.outcomes) for word in TROUBLE):
                examples.append(d.observation)
    step = max(1, len(examples) // ONE_MOVE_EXAMPLES)
    return {"advice": ONE_MOVE, "examples": examples[::step][:ONE_MOVE_EXAMPLES], "source": "multi"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-gap", type=float, default=0.25)
    parser.add_argument("--cap", type=float, default=2.0)
    args = parser.parse_args(argv)
    pairs = best_and_worst(args.run_dir, args.min_gap)
    session = spark_players.RetryingSession(spark_players.spark_session(RUN, args.cap))
    lessons: list[dict[str, Any]] = [one_move_lesson(args.run_dir)]
    unparsed = 0
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        for pair, job in [(p, pool.submit(mine_pair, session, p)) for p in pairs]:
            try:
                lessons += [
                    {"advice": a, "examples": [s], "source": pair[2]} for a, s in job.result()
                ]
            except MiningReplyError as error:
                unparsed += 1
                print(f"unparsed {pair[2]}: {error}", flush=True)
    args.out.write_text(
        json.dumps({"pairs": len(pairs), "unparsed": unparsed, "lessons": lessons}, indent=1)
    )
    print(f"{len(pairs)} pairs, {unparsed} unparsed, {len(lessons)} lessons", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
