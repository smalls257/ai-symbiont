"""The loop's memory between rounds: declared hold-out, kept cards, graded attempts, round log.

The held-out set is declared once, before round 0, by its sha; a different set later raises
`HeldOutChangedError`. Dropped lessons are retired for good. State is one local JSON file
outside the repo (card text included, mode 0600); `curve()` is the publishable part: counts,
ids and labels only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attempts import Attempt
from learners import Installed
from loop_cards import LessonCard
from utility import AblationPair, Exposure, Mark

# "Improved" means the held-out pass rate beats the start's by this much; a smaller gain is
# noise at 18-24 held-out tasks.
IMPROVE_SHARE = 0.10


class HeldOutChangedError(RuntimeError):
    """The domain's held-out set differs from the one declared before round 0."""


def held_out_sha(held_out: frozenset[str]) -> str:
    """A short hash of the sorted held-out ids: the declaration the later rounds must match."""
    return hashlib.sha256("\n".join(sorted(held_out)).encode()).hexdigest()[:16]


@dataclass
class Ledger:
    """Everything the loop knows after its last finished round."""

    domain: str
    declared_held_out: str
    held_out_count: int
    route: str
    start: str
    cards: dict[str, LessonCard] = field(default_factory=dict)
    retired: set[str] = field(default_factory=set)
    attempts: list[Attempt] = field(default_factory=list)
    exposures: dict[str, Exposure] = field(default_factory=dict)  # "lesson|attempt" -> exposure
    pairs: list[AblationPair] = field(default_factory=list)  # every round's, pooled for judging
    rounds: list[dict[str, Any]] = field(default_factory=list)
    rounds_trained: dict[str, int] = field(default_factory=dict)

    @classmethod
    def declare(cls, domain: str, held_out: frozenset[str], route: str, start: str) -> Ledger:
        """A new loop for one domain, route and start: the held-out set is fixed here."""
        if not held_out:
            raise HeldOutChangedError(f"{domain}: an empty held-out set cannot be declared")
        return cls(domain, held_out_sha(held_out), len(held_out), route, start)

    @property
    def key(self) -> str:
        """Where this loop's state lives: one ledger per domain, route and start."""
        return f"{self.domain}/{self.route}/{self.start}"

    def require_held_out(self, held_out: frozenset[str]) -> None:
        """Raise unless `held_out` is exactly the declared set."""
        if held_out_sha(held_out) != self.declared_held_out:
            raise HeldOutChangedError(
                f"{self.domain}: held-out set {held_out_sha(held_out)} ({len(held_out)} ids) is "
                f"not the one declared before round 0 ({self.declared_held_out}, "
                f"{self.held_out_count} ids)"
            )

    @property
    def next_round(self) -> int:
        """The index of the round to run next."""
        return len(self.rounds)

    def current(self, base: Installed) -> tuple[str, frozenset[str]]:
        """(arm, lesson ids it holds) of the last round; the start's base before round 0."""
        if not self.rounds:
            return base.arm, base.lessons
        last = self.rounds[-1]
        return last["model_out"], frozenset(last["trained_lessons"])

    def record_exposure(self, lesson_id: str, attempt: Attempt, mark: Mark) -> None:
        """Remember one lesson's mark on one attempt (computed once, reused every round)."""
        self.exposures[f"{lesson_id}|{attempt.attempt_id}"] = Exposure(
            lesson_id,
            attempt.attempt_id,
            attempt.task_id,
            mark,
            attempt.passed,
            lesson_id in attempt.trained_lessons,
        )

    def has_exposure(self, lesson_id: str, attempt_id: str) -> bool:
        """Whether that mark is already known."""
        return f"{lesson_id}|{attempt_id}" in self.exposures

    def to_json(self) -> dict[str, Any]:
        """The whole state, for `save`."""
        return {
            "domain": self.domain,
            "declared_held_out": self.declared_held_out,
            "held_out_count": self.held_out_count,
            "route": self.route,
            "start": self.start,
            "cards": [card.to_json() for card in self.cards.values()],
            "retired": sorted(self.retired),
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "exposures": [{**e.__dict__, "mark": str(e.mark)} for e in self.exposures.values()],
            "pairs": [p.__dict__ for p in self.pairs],
            "rounds": self.rounds,
            "rounds_trained": self.rounds_trained,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Ledger:
        """Inverse of `to_json`."""
        ledger = cls(
            raw["domain"], raw["declared_held_out"], raw["held_out_count"], raw["route"],
            raw["start"],
        )  # fmt: skip
        ledger.cards = {c["lesson_id"]: LessonCard.from_json(c) for c in raw["cards"]}
        ledger.retired = set(raw["retired"])
        ledger.attempts = [Attempt.from_json(a) for a in raw["attempts"]]
        for e in raw["exposures"]:
            exposure = Exposure(**{**e, "mark": Mark(e["mark"])})
            ledger.exposures[f"{exposure.lesson_id}|{exposure.attempt_id}"] = exposure
        ledger.rounds = raw["rounds"]
        ledger.rounds_trained = raw["rounds_trained"]
        ledger.pairs = [AblationPair(**p) for p in raw["pairs"]]
        return ledger


def ledger_path(state_dir: Path, key: str) -> Path:
    """Where a loop's ledger lives (key: domain/route/start)."""
    return state_dir / key / "ledger.json"


def load(state_dir: Path, key: str) -> Ledger | None:
    """The loop's ledger, or None before its first round."""
    path = ledger_path(state_dir, key)
    return Ledger.from_json(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def save(state_dir: Path, ledger: Ledger) -> Path:
    """Write the ledger atomically, readable by the owner only."""
    path = ledger_path(state_dir, ledger.key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger.to_json(), indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return path


def _rate(found: dict[str, int], arm: str) -> float:
    """Pass rate of one held-out arm; graded counts differ when attempts went ungraded."""
    graded = found[f"{arm}_graded"]
    return found[f"{arm}_passed"] / graded if graded else 0.0


def rounds_to_improve(ledger: Ledger, versus: str) -> dict[str, Any]:
    """Rounds and lessons until the round's held-out pass rate beats `versus` by IMPROVE_SHARE.

    `versus` is "start" or "plain"; None when no round has beaten it yet.
    """
    for entry in ledger.rounds:
        found = entry["eval"]
        if _rate(found, "adapter") - _rate(found, versus) >= IMPROVE_SHARE:
            return {
                "versus": versus,
                "rounds_to_improve": entry["round"] + 1,
                "lessons_to_improve": len(entry["trained_lessons"]),
                "needed_rate_gain": IMPROVE_SHARE,
            }
    return {"versus": versus, "rounds_to_improve": None, "lessons_to_improve": None}


def curve(ledger: Ledger) -> dict[str, Any]:
    """The publishable result: held-out pass counts per round, plain and the start beside each."""
    return {
        "label": "under test: recursive loop, held-out pass counts per round (plain is reference)",
        "domain": ledger.domain,
        "route": ledger.route,
        "start": ledger.start,
        "held_out_declared": ledger.declared_held_out,
        "held_out_tasks": ledger.held_out_count,
        "rounds_to_improve": [rounds_to_improve(ledger, arm) for arm in ("start", "plain")],
        "rounds": [
            {
                "round": entry["round"],
                "model": entry["model_out"],
                "train_mode": entry["manifest"]["train_mode"],
                "lessons_trained": len(entry["trained_lessons"]),
                **entry["eval"],
            }
            for entry in ledger.rounds
        ],
    }
