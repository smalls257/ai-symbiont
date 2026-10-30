"""Core D2 arm W: the two most similar earlier solved tasks of the same repository, as text.

Similarity is word overlap (Jaccard) of the issue texts. Each example is the issue plus the
commands the teacher ran and the start of each result, cut to a budget so two examples stay near
6k tokens. Pure: callers pass rows and parsed trajectories. Descriptive arm; it never trains.
"""

import re
from collections.abc import Sequence

WORDS = re.compile(r"[a-z_][a-z0-9_]{2,}")
EXAMPLES = 2  # prereg W: the 2 most similar earlier tasks
CHARS_PER_EXAMPLE = 10_500  # about 3k tokens at 3.5 characters a token; two examples near 6k
RESULT_CHARS = 300  # how much of each command's result to keep


def words(text: str) -> set[str]:
    return set(WORDS.findall(text.lower()))


def similarity(first: str, second: str) -> float:
    """Jaccard overlap of the two texts' words; 0.0 when either is empty."""
    left, right = words(first), words(second)
    return len(left & right) / len(left | right) if left and right else 0.0


def most_similar(issue: str, earlier: Sequence[dict], count: int = EXAMPLES) -> list[dict]:
    """The `count` earlier rows (instance_id, problem_statement) closest to `issue`, ties by id."""
    ranked = sorted(
        earlier, key=lambda row: (-similarity(issue, row["problem_statement"]), row["instance_id"])
    )
    return list(ranked[:count])


def render_steps(messages: Sequence[dict], budget: int) -> str:
    """The assistant's commands, each followed by the start of its result, within `budget` chars."""
    out, used = [], 0
    for message in messages:
        text = (
            message["content"] if isinstance(message["content"], str) else str(message["content"])
        )
        part = text[:RESULT_CHARS] if message["role"] != "assistant" else text
        if message["role"] == "system":
            continue
        if used + len(part) > budget:
            break
        out.append(f"[{message['role']}] {part}")
        used += len(part)
    return "\n".join(out)


def example_block(rows_and_messages: Sequence[tuple[dict, Sequence[dict]]]) -> str:
    """The text prepended to the task: each example's issue then its commands and results."""
    parts = ["Here are two solved earlier issues of this repository, for reference:"]
    for number, (row, messages) in enumerate(rows_and_messages, 1):
        issue = row["problem_statement"][:1500]
        steps = render_steps(messages, CHARS_PER_EXAMPLE - len(issue))
        parts.append(f"--- Example {number}: {row['instance_id']}\nIssue: {issue}\nSteps:\n{steps}")
    return "\n\n".join(parts) + "\n\nNow solve this issue:\n\n"
