"""The text of one step for the T49 ceiling probe: what was done and a short cut of what came back.

The embedder reads at most 256 word pieces, so whole observations would bury the error under
file listings: each step keeps its action up to a cap and only the head and tail of its
observation, where a command's error and exit marker sit. Embedded locally, never printed or logged.
"""

from symbiont.records.schema import Kind, Record

ACTION_CHARS = 200  # a long heredoc command is cut: the head names the tool and its target
HEAD_CHARS = 250  # first characters of the observation: the start of the output or error
TAIL_CHARS = 250  # last characters: the traceback's last line and the exit-code marker
GAP = " ... "


def step_text(record: Record) -> str:
    """The action and a head-and-tail snippet of the observation, as one string."""
    return f"{_action(record)}\n{snippet(record.raw)}".strip()


def snippet(raw: str) -> str:
    """`raw` whole if short, else its first HEAD_CHARS and last TAIL_CHARS characters."""
    if len(raw) <= HEAD_CHARS + TAIL_CHARS + len(GAP):
        return raw
    return raw[:HEAD_CHARS] + GAP + raw[-TAIL_CHARS:]


def _action(record: Record) -> str:
    if record.kind is Kind.COMMAND and record.command is not None:
        return f"$ {record.command[:ACTION_CHARS]}"
    if record.files:
        return f"{record.kind.value} {' '.join(record.files)[:ACTION_CHARS]}"
    return record.kind.value
