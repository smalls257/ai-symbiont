"""One synchronous Freedoom episode (periphery: ViZDoom, the model endpoint, files).

The model reads `describe(state)` and replies with a strategy of scripted
moves; `execute_move` carries each one out against the live game. Invalid
model replies are recorded as rejected, never replaced by a default move.
Plays Freedoom via ViZDoom. Moves are scripted, and every log line says so.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from symbiont.act1.engine import (
    KeyTracker,
    SectorConvention,
    button_vector,
    check_sector_convention,
    make_game,
    view_from_engine,
)
from symbiont.act1.env_text import (
    GameStateView,
    describe,
    route_hints,
)
from symbiont.act1.glimmer import Reply, ReplyFn, chat_reply
from symbiont.act1.map_index import MapIndex, build_index
from symbiont.act1.moves import Button, Done
from symbiont.act1.navmap import NavMap, build_navmap
from symbiont.act1.steplog import Decision, MoveRun, kind_of
from symbiont.act1.strategy import Move, StrategyError, parse_strategy
from symbiont.act1.wad import read_map

# Progress goes to the logging module (Sensor); the game text itself is in the run log under runs/.
progress = logging.getLogger(__name__)
HISTORY_IN_PROMPT = 6


def build_prompt(observation: str, history: list[str]) -> str:
    """The text the model sees: move rules, recent history, then the observation."""
    return (
        "You play a Freedoom level through a text description. Goal: find keys and doors, "
        "reach the exit, shoot enemies that threaten you. You do not press buttons: you choose "
        "a short strategy of SCRIPTED moves (1 to 3), one per line, and the scripts carry them "
        "out. Allowed moves:\n"
        "  walk_to(ObjectName)   walk to a visible object, a door (write: walk_to(door)) "
        "or the exit (walk_to(exit))\n"
        "  go_to(door|exit|key|ObjectName)  route around walls to the nearest such thing, "
        "even out of view, opening doors on "
        'the way; "Reachable with go_to" lists them with path distances\n'
        "  open_door()           walk to the nearest door and press USE; "
        "reports opened, locked or did not open\n"
        "  turn(degrees)         positive turns left, negative right\n"
        "  shoot_nearest()       aim at and shoot the nearest visible enemy\n"
        "  retreat_to(ObjectName) move to a visible object, backing off from close enemies\n"
        "Reply with only the move lines.\n\nRecent scripted moves:\n"
        + ("\n".join(history[-HISTORY_IN_PROMPT:]) or "(none)")
        + "\n\nNow: "
        + observation
    )


def execute_move(
    move: Move,
    observe: Callable[[], GameStateView | None],
    act: Callable[[frozenset[Button]], None],
) -> str:
    """Run one scripted move to completion; returns why it stopped."""
    for _ in range(move.max_tics):
        state = observe()
        if state is None:
            return "episode ended"
        result = move.step(state)
        if isinstance(result, Done):
            return result.reason
        act(result)
    return f"timeout after {move.max_tics} tics"


# --- the loop ------------------------------------------------------------------------------------


def _classify(reply: Reply, nav: NavMap | None = None) -> tuple[list[Move] | None, str, str | None]:
    """(moves, status, rejection reason). A truncated reply is never parsed."""
    if reply.finish_reason == "length":
        return (
            None,
            "truncated",
            f"reply cut off by the token limit after {reply.reasoning_chars} reasoning chars",
        )
    try:
        return parse_strategy(reply.text, nav), "ok", None
    except StrategyError as error:
        return None, "invalid", str(error)


@dataclass(frozen=True)
class RunLog:
    """Where decisions are appended, the run header, and who hears of each played move.

    No path: no log file. No `on_move`: no extra observation per move. The observer lives here
    because `run_episode` is at its five-parameter cap.
    """

    path: Path | None = None
    header: dict[str, Any] = field(default_factory=dict)
    on_move: Callable[[MoveRun], None] | None = None


@dataclass(frozen=True)
class MapKnowledge:
    """What the runner knows about the level: the WAD index and, optionally, the route graph."""

    index: MapIndex
    nav: NavMap | None = None


class _Session:
    """The live game seen through the key tracker; the two callables the scripted moves need."""

    def __init__(
        self,
        game: Any,
        knowledge: MapKnowledge,
        on_move: Callable[[MoveRun], None] | None,
        convention: SectorConvention,
    ):
        """Wrap a live game with its map knowledge, key tracker and sector convention."""
        self.game, self.knowledge, self.keys = game, knowledge, KeyTracker()
        self.on_move, self.tics, self.decision = on_move, 0, 0
        self.convention = convention

    def observe(self) -> GameStateView | None:
        """The current game state as the model's view, or None once the episode is finished."""
        if self.game.is_episode_finished():
            return None
        return view_from_engine(
            self.game.get_state(), self.keys, self.knowledge.index, convention=self.convention
        )

    def act(self, buttons: frozenset[Button]) -> None:
        """Press the buttons for one tic."""
        self.game.make_action(button_vector(buttons))
        self.tics += 1


def _open_run_log(
    run_log: RunLog, max_decisions: int, convention: SectorConvention
) -> IO[str] | None:
    """Open the log in append mode with a header line, so reruns never erase evidence."""
    if run_log.path is None:
        return None
    run_log.path.parent.mkdir(parents=True, exist_ok=True)
    handle = run_log.path.open("a")
    started_at = datetime.now(UTC).isoformat()
    run_header = {
        **run_log.header,
        "started_at": started_at,
        "max_decisions": max_decisions,
        "sector_convention": convention.value,
    }
    handle.write(json.dumps({"run_header": run_header}) + "\n")
    handle.flush()
    return handle


def rejected_line(rejected: str | None) -> str:
    """The history line a rejected reply leaves; the loop and history_before share it."""
    return f"(rejected reply: {rejected})"


def history_before(decisions: Sequence[Decision], index: int) -> list[str]:
    """The move history the loop had when it asked for decision `index` (prompts rebuilt from logs).

    Raises IndexError when `index` is not a logged decision.
    """
    if not 0 <= index < len(decisions):
        raise IndexError(f"decision {index} is not among {len(decisions)} logged decisions")
    history: list[str] = []
    for decision in decisions[:index]:
        history.extend(
            decision.outcomes if decision.status == "ok" else [rejected_line(decision.rejected)]
        )
    return history


def _carry_out(
    moves: list[Move] | None, rejected: str | None, session: _Session, history: list[str]
) -> list[str]:
    """Run the parsed moves; a rejected reply goes to the history, never replaced by a move."""
    if moves is None:
        history.append(rejected_line(rejected))
        return []
    outcomes = []
    for move in moves:
        outcome = _play(move, session)
        outcomes.append(f"{move.label} -> {outcome}")
        history.append(outcomes[-1])
    return outcomes


def _play(move: Move, session: _Session) -> str:
    """Execute one move; tell the observer, if any, what it did between two observations."""
    if session.on_move is None:
        return execute_move(move, session.observe, session.act)
    before, started = session.observe(), session.tics
    outcome = execute_move(move, session.observe, session.act)
    if before is not None:
        session.on_move(
            MoveRun(
                session.decision, move.label, kind_of(move), outcome,
                session.tics - started, before, session.observe(),
            )
        )  # fmt: skip
    return outcome


def _decide(
    number: int, session: _Session, reply_fn: ReplyFn, history: list[str]
) -> Decision | None:
    """One model decision; None when the episode has ended."""
    state = session.observe()
    if state is None:
        return None
    session.decision = number
    nav = session.knowledge.nav
    observation = describe(replace(state, routes=route_hints(nav, state)) if nav else state)
    started = time.monotonic()
    reply = reply_fn(build_prompt(observation, history))
    seconds = time.monotonic() - started
    moves, status, rejected = _classify(reply, nav)
    outcomes = _carry_out(moves, rejected, session, history)
    tokens = reply.tokens
    return Decision(
        number, observation, reply.text, status, rejected, reply.finish_reason,
        reply.reasoning_chars, tuple(outcomes), seconds,
        None if tokens is None else tokens.prompt, None if tokens is None else tokens.completion,
    )  # fmt: skip


def run_episode(
    game: Any,
    reply_fn: ReplyFn,
    max_decisions: int,
    run_log: RunLog | None = None,
    *,
    knowledge: MapKnowledge,
) -> list[Decision]:
    """Play up to `max_decisions` model decisions, appending each to the run log as it finishes."""
    run_log = run_log or RunLog()
    game.new_episode()
    convention = check_sector_convention(knowledge.index.sectors, game.get_state().sectors)
    progress.info("sector convention: %s", convention.value)
    session = _Session(game, knowledge, run_log.on_move, convention)
    log = _open_run_log(run_log, max_decisions, convention)
    history: list[str] = []
    decisions: list[Decision] = []
    try:
        for number in range(max_decisions):
            decision = _decide(number, session, reply_fn, history)
            if decision is None:
                break
            decisions.append(decision)
            if log is not None:
                log.write(json.dumps(asdict(decision)) + "\n")
                log.flush()
            progress.info(
                "[%d] %5.1fs %s %s",
                number,
                decision.model_seconds,
                decision.status,
                list(decision.outcomes),
            )
    finally:
        if log is not None:
            log.close()
    return decisions


def load_run_log(path: Path) -> list[Decision]:
    """The decisions of the log's last run: a rerun appends after a new header line."""
    decisions: list[Decision] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry: dict[str, Any] = json.loads(line)
        if "run_header" in entry:
            decisions = []
            continue
        decisions.append(Decision(**{**entry, "outcomes": tuple(entry["outcomes"])}))
    return decisions


def share_without_objects_or_doors(decisions: list[Decision]) -> float:
    """Fraction of observations with no objects, doors or exits (day-1 'nothing notable')."""
    if not decisions:
        return 0.0
    return sum("No objects, doors or exits in view" in d.observation for d in decisions) / len(
        decisions
    )


def _play_from_the_command_line(decisions_wanted: int, base_url: str, model: str) -> None:
    """Play MAP01 with a Glimmer model from the command line, for development."""
    from symbiont.act1.setup_assets import install_freedoom

    wad = install_freedoom(Path("data") / "freedoom")
    geometry = read_map(wad.read_bytes(), "MAP01")
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    run_log = RunLog(Path("runs") / "act1_episode.jsonl", {"model": model, "base_url": base_url})
    game = make_game(wad)
    try:
        done = run_episode(
            game,
            lambda prompt: chat_reply(base_url, model, prompt),
            decisions_wanted,
            run_log,
            knowledge=knowledge,
        )
    finally:
        game.close()
    progress.info(
        "DONE decisions=%d invalid=%d truncated=%d no_objects_or_doors=%.0f%%",
        len(done),
        sum(d.status == "invalid" for d in done),
        sum(d.status == "truncated" for d in done),
        100 * share_without_objects_or_doors(done),
    )


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _play_from_the_command_line(
        int(sys.argv[1]) if len(sys.argv) > 1 else 10,
        sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8081/v1",
        sys.argv[3] if len(sys.argv) > 3 else "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M",
    )
