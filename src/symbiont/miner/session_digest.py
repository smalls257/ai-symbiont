"""A session squeezed to what a model needs to name it: asks, files, failures, ending, pushback.

A summary of a first message that reads "This session is being continued..." or "ok" says
nothing, so injected text and chat are skipped and the ending is kept: without the last turns the
dry run on 365 real sessions could not tell done from stuck. Text is scrubbed
(`miner.secrets`) before it leaves. Pure: records in, digest out.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.attempts import failed
from symbiont.miner.secrets import scrub
from symbiont.miner.signals.correction import CORRECTION_TAGS
from symbiont.miner.struggle import started_day
from symbiont.miner.themes import Codebase
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG
from symbiont.records.schema import Kind, Record
from symbiont.records.session_tags import TITLE_PREFIX, tag_values

# Caps from the failure-cards plan (Task 8); median digest on cipher-box was 76 words [measured].
MAX_ASKS = 2
MAX_FILES = 5
MAX_FAILED = 3
MAX_CORRECTIONS = 3
MAX_LAST_TURNS = 2
ASK_CHARS = 160
CORRECTION_CHARS = 140
TURN_CHARS = 160
TITLE_CHARS = 100
COMMAND_WORDS = 4
COMMAND_CHARS = 60
MIN_ASK_WORDS = 4  # shorter turns in the dry run were "ok", "yes", "continue"
UNDATED = "date unknown"
_MARKUP = re.compile(r"<[^>]+>[^<]*</[^>]+>|<[^>]+>")
_CHAT = re.compile(
    r"^(ok|okay|yes|yeah|yep|sure|thanks|great|cool|nice|continue|go ahead)\b", re.IGNORECASE
)
_INJECTED = ("This session is being continued", "[Request interrupted", "Caveat:")
_COMMAND_NAME = re.compile(r"<command-name>\s*([^<\s]+)\s*</command-name>")
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_PLAN = "Implement the following plan"
_PLAN_HEADING = re.compile(r"^#+\s*(?:Plan:\s*)?(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class SessionDigest:
    """The few lines of one session a summarizing model reads."""

    session_id: str
    date: str
    title: str
    asks: tuple[str, ...]
    files: tuple[str, ...]
    failed: tuple[str, ...]
    corrections: tuple[str, ...]
    last_turns: tuple[str, ...]


def digest_of(session: Sequence[Record], codebase: Codebase) -> SessionDigest:
    """The digest of one session (records in step order)."""
    return SessionDigest(
        session_id=session[0].session_id,
        date=started_day(session) or UNDATED,
        title=_title(session),
        asks=_asks(session),
        files=_files(session, codebase),
        failed=_failed(session),
        corrections=tuple(text for _, text in session_corrections(session))[:MAX_CORRECTIONS],
        last_turns=_last_turns(session),
    )


def session_corrections(session: Sequence[Record]) -> list[tuple[int, str]]:
    """(step, scrubbed text) of the user turns tagged as pushback, injected text left out."""
    return [
        (record.step, scrub(text)[:CORRECTION_CHARS])
        for record in _typed_turns(session)
        if CORRECTION_TAGS & set(record.tags)
        if (text := _clean(record.raw))
    ]


def typed_message(record: Record) -> str | None:
    """What the developer typed in a user turn, or None for text the harness injected.

    A slash command reads as the command ("/compact"); local command output, caveats and
    summaries of an earlier session are None, so a page never lists them as your messages.
    """
    if record.kind != Kind.USER_TURN or OUR_OUTPUT_RECORD_TAG in record.tags:
        return None
    named = _COMMAND_NAME.search(record.raw)
    if named:
        args = _COMMAND_ARGS.search(record.raw)
        return " ".join((named.group(1), *(args.group(1).split() if args else ())))
    return None if _is_injected(_clean(record.raw)) else record.raw


def _typed_turns(session: Sequence[Record]) -> list[Record]:
    """User turns the developer typed: not our own output, not text a harness injected."""
    return [
        record
        for record in session
        if record.kind == Kind.USER_TURN
        and OUR_OUTPUT_RECORD_TAG not in record.tags
        and not _is_injected(_clean(record.raw))
    ]


def _clean(raw: str) -> str:
    return " ".join(_MARKUP.sub(" ", raw).split())


def _is_injected(text: str) -> bool:
    return not text or text.startswith(_INJECTED)


def _title(session: Sequence[Record]) -> str:
    tags = tuple(tag for record in session for tag in record.tags)
    named = tag_values(tags, TITLE_PREFIX)[:1]
    if named:
        return scrub(named[0])[:TITLE_CHARS]
    plans = (r.raw for r in session if r.kind == Kind.USER_TURN and r.raw.startswith(_PLAN))
    heading = next((found.group(1) for raw in plans if (found := _PLAN_HEADING.search(raw))), "")
    return scrub(heading.strip())[:TITLE_CHARS]


def _asks(session: Sequence[Record]) -> tuple[str, ...]:
    asked = []
    for record in _typed_turns(session):
        text = _clean(record.raw)
        if CORRECTION_TAGS & set(record.tags) or text.startswith(_PLAN):
            continue
        if len(text.split()) >= MIN_ASK_WORDS and not _CHAT.match(text):
            asked.append(scrub(text)[:ASK_CHARS])
    return tuple(asked[:MAX_ASKS])


def _files(session: Sequence[Record], codebase: Codebase) -> tuple[str, ...]:
    edited = Counter(
        relative
        for record in session
        if record.kind == Kind.EDIT and record.exit_code != 1
        for path in record.files
        if (relative := codebase.relative(path))
    )
    return tuple(name for name, _ in edited.most_common(MAX_FILES))


def _failed(session: Sequence[Record]) -> tuple[str, ...]:
    counts = Counter(
        " ".join((record.command or "").split()[:COMMAND_WORDS])[:COMMAND_CHARS]
        for record in session
        if failed(record)
    )
    return tuple(scrub(f"{command} (x{n})") for command, n in counts.most_common(MAX_FAILED))


def _last_turns(session: Sequence[Record]) -> tuple[str, ...]:
    spoken = [
        (record, _clean(record.raw))
        for record in session
        if record.kind in (Kind.USER_TURN, Kind.AGENT_TURN)
        and OUR_OUTPUT_RECORD_TAG not in record.tags
    ]
    ending = [(r, text) for r, text in spoken if text and not _is_injected(text)]
    return tuple(_spoken_line(record, text) for record, text in ending[-MAX_LAST_TURNS:])


def _spoken_line(record: Record, text: str) -> str:
    speaker = "developer" if record.kind == Kind.USER_TURN else "agent"
    return scrub(f"{speaker}: {text}")[:TURN_CHARS]
