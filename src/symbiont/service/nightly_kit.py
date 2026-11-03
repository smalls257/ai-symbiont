"""The judge kit: the fixed general-judge base and the two replay files a night starts from.

If a piece is missing, the night would train a different judge than the one measured, so
`open_kit` raises and names it. A kit folder holds `base/` (the merged general judge, a model
folder), `general-rows.jsonl` (round-3 judge rows) and `habits.jsonl` (habit rows).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from symbiont.service.nightly_rows import ChatRow

BASE = "base"
GENERAL_ROWS = "general-rows.jsonl"
HABITS = "habits.jsonl"
BASE_MARKER = "config.json"


class JudgeKitError(FileNotFoundError):
    """The kit is missing a piece or holds an unreadable one; the message names it."""


@dataclass(frozen=True)
class JudgeKit:
    """Where the fixed base and the two replay files are."""

    base: Path
    general_rows: Path
    habits: Path


def open_kit(root: Path) -> JudgeKit:
    """The kit at `root`, or JudgeKitError naming every missing piece."""
    wanted = {
        root / BASE / BASE_MARKER: "the merged general judge (a model folder)",
        root / GENERAL_ROWS: "the general judge rows",
        root / HABITS: "the habit rows",
    }
    missing = [f"{path} ({what})" for path, what in wanted.items() if not path.is_file()]
    if missing:
        raise JudgeKitError(
            "the judge kit at " + str(root) + " is incomplete: missing " + "; ".join(missing)
        )
    return JudgeKit(root / BASE, root / GENERAL_ROWS, root / HABITS)


def read_rows(path: Path) -> list[ChatRow]:
    """Every chat row of a JSONL file.

    Raises JudgeKitError naming the file and line of a bad row, and for a file with no rows.
    """
    rows: list[ChatRow] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if [m["role"] for m in row["messages"]] != ["system", "user", "assistant"]:
                raise ValueError("expected system, user, assistant messages")
        except (ValueError, KeyError, TypeError) as bad:
            raise JudgeKitError(f"{path}:{number}: not a chat row ({bad})") from bad
        rows.append(row)
    if not rows:
        raise JudgeKitError(f"{path} has no rows")
    return rows
