"""Run state for Evolve: state.json (identity, seeds, journaled generations, games) and events.

Everything the run must not lose lives here, outside the repo, mode 0600, replaced atomically per
write. A resumed run reads it back: finished games are served from the file, a generation's
children are reused as written, and a different player, author, model or reasoning is refused.
"""

import dataclasses
import json
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1.card_genome import Card  # noqa: E402 - needs the sibling path added above
from symbiont.act1.evolution import Player  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.lineage import Arm, Birth, birth_from_json, birth_to_json  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402


def game_key(card_id: str, case: Case) -> str:
    """The stable key of one game in the state file."""
    return f"{card_id}|{case.level}|{case.seed}|{case.skill}|{case.cuts.value}"


def result_to_json(result: GameResult) -> dict[str, Any]:
    """A game result as plain JSON."""
    out = dataclasses.asdict(result)
    out["grade"] = result.grade.value
    out["case"]["cuts"] = result.case.cuts.value
    out["pains"] = [list(pair) for pair in result.pains]
    return out


def result_from_json(data: dict[str, Any]) -> GameResult:
    """The inverse of result_to_json."""
    case = Case(**{**data["case"], "cuts": CutSetting(data["case"]["cuts"])})
    fields = {**data, "case": case, "grade": Grade(data["grade"])}
    fields["pains"] = tuple((name, count) for name, count in data["pains"])
    return GameResult(**fields)


class PlayerChangedError(RuntimeError):
    """A run was resumed with a different player, author, model or reasoning than it began with."""


class NullLedger:
    """The spend ledger of a run that makes no paid call (fake and scripted players)."""

    def snapshot(self) -> dict[str, Any]:
        """Calls and dollars so far, from the ledger itself."""
        return {"calls": 0, "dollars": 0.0, "source": "ledger: this run makes no paid calls"}


class RunLedger:
    """The shared spend ledger file read for one run: the lines that carry its name."""

    def __init__(self, run: str) -> None:
        """Read the default ledger path; the run name picks this run's lines."""
        from symbiont.egress.spend import Ledger

        self.run, self.ledger = run, Ledger()

    def snapshot(self) -> dict[str, Any]:
        """Calls and dollars the run has spent, and the total across all runs."""
        rows = [row for row in self.ledger.entries() if row["run"] == self.run]
        return {
            "calls": len(rows),
            "dollars": round(sum(row["cost_usd"] for row in rows), 4),
            "all_runs_dollars": round(self.ledger.spent(), 4),
            "source": "spend ledger file, lines of this run",
        }


class RunStore:
    """state.json (mode 0600, atomic) and events.jsonl for one run; also the generation journal.

    state.json holds: the run's identity (player, author, model, reasoning), the seed cards, every
    generation's children written down before any of its games, and every finished game.
    """

    def __init__(self, directory: Path) -> None:
        """Create the run directory and read any earlier state."""
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path, self.events_path = directory / "state.json", directory / "events.jsonl"
        stored = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.games: dict[str, dict[str, Any]] = stored.get("games", {})
        self.cards: dict[str, str] = stored.get("cards", {})
        self.identity: dict[str, Any] | None = stored.get("identity")
        self.seed_cards: list[Any] | None = stored.get("seed_cards")
        self.generations: dict[str, Any] = stored.get("generations", {})

    def _write(self) -> None:
        """Replace state.json atomically with mode 0600."""
        document = {
            "identity": self.identity,
            "seed_cards": self.seed_cards,
            "generations": self.generations,
            "games": self.games,
            "cards": self.cards,
        }
        fd, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump(document, handle)
        Path(name).chmod(0o600)
        Path(name).replace(self.state_path)

    def require_identity(self, identity: dict[str, Any]) -> None:
        """Remember who plays and writes; refuse to resume with anyone else."""
        if self.identity is not None and self.identity != identity:
            raise PlayerChangedError(f"run began with {self.identity}, resumed with {identity}")
        self.identity = identity
        self._write()

    def seeds(self, build: Callable[[], list[Card]]) -> list[Card]:
        """The seed cards: stored on the first call, read back on a resume."""
        if self.seed_cards is None:
            self.seed_cards = [card.to_json() for card in build()]
            self._write()
        return [Card.from_json(item) for item in self.seed_cards]

    def load(self, arm: Arm, generation: int) -> tuple[tuple[Card, ...], tuple[Birth, ...]] | None:
        """The generation's stored children and births, or None."""
        found = self.generations.get(f"{arm.value}:{generation}")
        if found is None:
            return None
        cards = tuple(Card.from_json(item) for item in found["cards"])
        return cards, tuple(birth_from_json(item) for item in found["births"])

    def save(
        self, arm: Arm, generation: int, cards: tuple[Card, ...], births: tuple[Birth, ...]
    ) -> None:
        """Write a generation's children down before any game of it is played."""
        self.generations[f"{arm.value}:{generation}"] = {
            "cards": [card.to_json() for card in cards],
            "births": [birth_to_json(birth) for birth in births],
        }
        self._write()

    def save_game(self, key: str, result: GameResult, card: Card) -> None:
        """Record one game with who played it, and the card's text for the owner."""
        self.games[key] = {**result_to_json(result), "player": self.identity}
        self.cards[card.card_id] = card.render()
        self._write()

    def event(self, name: str, **fields: Any) -> None:
        """Append one timing or stage event."""
        line = json.dumps({"event": name, "at": time.time(), **fields})
        with self.events_path.open("a") as handle:
            handle.write(line + "\n")


class ResumingPlayer:
    """Returns a stored game instead of replaying it, and stores every new one as it finishes."""

    def __init__(self, inner: Player, store: RunStore) -> None:
        """Wrap a player; `replayed` counts games served from the state file."""
        self.inner, self.store, self.replayed = inner, store, 0

    def _stored(self, card: Card, case: Case) -> GameResult | None:
        """The game from the state file, or None."""
        found = self.store.games.get(game_key(card.card_id, case))
        if found is None:
            return None
        self.replayed += 1
        return result_from_json({k: v for k, v in found.items() if k != "player"})

    def _keep(self, card: Card, case: Case, result: GameResult, started: float) -> None:
        """Store a finished game and log its timing."""
        self.store.save_game(game_key(card.card_id, case), result, card)
        self.store.event(
            "game", card=card.card_id, level=case.level, seed=case.seed,
            grade=result.grade.value, seconds=round(time.monotonic() - started, 3),
        )  # fmt: skip

    def play(self, card: Card, case: Case) -> GameResult:
        """One game, from the state file if it was already played."""
        stored = self._stored(card, case)
        if stored is not None:
            return stored
        started = time.monotonic()
        result = self.inner.play(card, case)
        self._keep(card, case, result, started)
        return result

    def play_many(
        self,
        pairs: Sequence[tuple[Card, Case]],
        on_result: Callable[[Card, Case, GameResult], None],
    ) -> None:
        """Serve stored games, then let the inner player play the rest as one batch."""
        missing = []
        for card, case in pairs:
            stored = self._stored(card, case)
            if stored is None:
                missing.append((card, case))
            else:
                on_result(card, case, stored)
        started = time.monotonic()

        def finished(card: Card, case: Case, result: GameResult) -> None:
            self._keep(card, case, result, started)
            on_result(card, case, result)

        many = getattr(self.inner, "play_many", None)
        if many is not None and missing:
            many(missing, finished)
        else:
            for card, case in missing:
                finished(card, case, self.inner.play(card, case))
