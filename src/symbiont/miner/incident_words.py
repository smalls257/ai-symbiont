"""The sentences of an incident card, in the developer's language and never the miner's.

Templates only: deciding what an incident is lives in `incidents.py`. A sentence names what the
agent did and what came of it, never an exit code, a grouping key or a threshold.
"""

import re

from symbiont.miner.failure_keys import EXIT_MEANINGS, broke_in_words, is_bare_exit
from symbiont.miner.resolutions import NOTHING_CHANGED, ONLY_UNRELATED_CHANGED, PASSED_RESPELLED
from symbiont.miner.screen import INLINE_TARGET
from symbiont.miner.secrets import scrub

# The most common openers of SWE-chat corrections that carry no instruction (cipher-box: 275 of
# 1,396 started with "ok") [measured], plus the words that go with them.
ACKNOWLEDGMENTS = frozenset(
    [
        "ok",
        "okay",
        "yes",
        "yeah",
        "yep",
        "sure",
        "thanks",
        "thank",
        "please",
        "go",
        "ahead",
        "continue",
        "proceed",
        "cool",
        "great",
        "nice",
        "perfect",
    ]
)
# Fewer real words than this after the acknowledgments and markup, and nobody was corrected.
MIN_REAL_WORDS = 3
QUOTE_CHARS = 160
DETAIL_LIMIT = 90
COMMAND_CHARS = 60
_MARKUP = re.compile(r"<(command-[\w-]+)[^>]*>.*?</\1>|<[^>]+>", re.S)
_SLASH_COMMAND = re.compile(r"(?<!\S)/[\w:-]+(?=\s|$)")
_WORD = re.compile(r"[A-Za-z']+")
_BAD_PATH = EXIT_MEANINGS[("pytest", 4)]
_NO_TESTS = EXIT_MEANINGS[("pytest", 5)]
_NO_RETRY_FIX = {
    NOTHING_CHANGED: "Nothing: it passed when run again.",
    PASSED_RESPELLED: "Nothing: it passed when run again.",
    ONLY_UNRELATED_CHANGED: "Unclear: it passed later, but only unrelated changes came between.",
}


def is_empty_correction(text: str) -> bool:
    """True when `text` holds no instruction: acknowledgments, slash commands and markup only."""
    bare = _SLASH_COMMAND.sub(" ", _MARKUP.sub(" ", text))
    words = [word.lower().strip("'") for word in _WORD.findall(bare)]
    return sum(word not in ACKNOWLEDGMENTS for word in words) < MIN_REAL_WORDS


def failure_sentence(program: str, target: str, broke: str, detail: str) -> str:
    """What the agent ran and how it went wrong, as one sentence ending in a period."""
    detail = detail.removeprefix(f"{broke}:").strip()
    where = _where(target)
    subject = f"an inline {program} script" if target == INLINE_TARGET else f"{program}{where}"
    if broke == _BAD_PATH:
        return f"The agent ran {program} on tests that do not exist{_in_brackets(target)}."
    if broke == _NO_TESTS:
        return f"The agent ran {program} and it found no tests to run{_in_brackets(target)}."
    if broke == "FileNotFoundError":
        return f"The agent ran {program} on a file that does not exist{_in_brackets(target)}."
    if broke == "ModuleNotFoundError":
        return f"The agent ran {subject}, but a module it needs is not installed."
    if broke.endswith(("Error", "Exception")):
        return _sentence(f"The agent ran {subject} and it stopped with {broke}", detail)
    if is_bare_exit(broke):
        return f"The agent ran {subject} and it failed."
    return _sentence(f"The agent ran {subject} and it failed", broke_in_words(broke))


def quoted_words(text: str) -> str:
    """`text` on one line, secrets scrubbed, cut to at most QUOTE_CHARS characters."""
    flat = scrub(" ".join(text.split()))
    return flat if len(flat) <= QUOTE_CHARS else flat[: QUOTE_CHARS - 3] + "..."


_LEADING_CD = re.compile(r"^\s*cd\s+\S+\s*&&\s*")


def without_cd(command: str) -> str:
    """`command` without the `cd <dir> &&` an agent puts before it: the program is the point."""
    return _LEADING_CD.sub("", command) if _LEADING_CD.match(command) else command


def command_example(command: str | None) -> str:
    """A failing command line as a group title; empty when the record is gone."""
    return quoted_words(without_cd(command or ""))


def correction_sentence(text: str) -> str:
    """The developer's correction, scrubbed and quoted to at most QUOTE_CHARS characters."""
    return f'You corrected the agent: "{quoted_words(text)}"'


def edited_then_passed(path: str, *, script: bool) -> str:
    """The fix when an edit to the codebase came between the failure and the pass."""
    return f"Edited {path}, then the {'script' if script else 'command'} passed."


def corrected_command_sentence(command: str) -> str:
    """The fix when the same program was run correctly after a wrong invocation."""
    return f"Ran the corrected command instead: {command}."


def setup_sentence(command: str) -> str:
    """The fix when the session ran a setup command before the pass."""
    return f"Fixed the setup: ran `{command}`, then it passed."


def passed_later_sentence(steps: str) -> str:
    """The fix when something other than a codebase edit came before the pass."""
    return f"It passed later, after the agent {steps}."


def unresolved_sentence(reason: str | None) -> str:
    """The fix line of a failure the history never shows fixed, or only passed unchanged."""
    return _NO_RETRY_FIX.get(reason or "", "Never fixed in this session.")


def edit_sentence(path: str) -> str:
    """What the agent edited."""
    return f"The agent edited {path or 'a file'}."


def ran_sentence(command: str, *, failed: bool) -> str:
    """What the agent ran, with or without the failure."""
    first = (scrub(command).strip().splitlines() or [""])[0]
    short = first if len(first) <= COMMAND_CHARS else first[: COMMAND_CHARS - 3] + "..."
    return f"The agent ran `{short}`" + (", which failed." if failed else ".")


def next_edit_sentence(path: str | None) -> str:
    """What the agent did after the correction."""
    return f"The agent then edited {path}." if path else "Nothing visible after your correction."


def trigger_phrase(kind: str, program: str, path: str) -> str:
    """The plain phrase a trigger is spoken as."""
    if kind == "before":
        return f"before {program}"
    if kind == "editing":
        return f"when editing {path}" if path else "when editing files"
    return f"when running {program}" + (f" on {path}" if path else "")


def _where(target: str) -> str:
    return "" if target in ("-", INLINE_TARGET) else f" on {target}"


def _in_brackets(target: str) -> str:
    return "" if target in ("-", INLINE_TARGET) else f" ({target})"


def _sentence(head: str, detail: str) -> str:
    return f"{head}: {detail.rstrip('. ')}." if detail else f"{head}."


NOISE_PHRASES = {  # keyed by NoiseReason value; the enum lives in incidents.py
    "look_around": "the agent was feeling its way around with a read-only command",
    "interrupt": "someone stopped the command; it did not break",
    "throwaway_script": "the agent's own throwaway script: its name repeats, its problem does not",
    "deliberate_repro": "the agent wrote a script to reproduce a bug, then fixed the code",
    "plain_retry": "it passed when run again with nothing worth learning changed",
    "empty_correction": "an acknowledgment or a slash command, not a correction",
}
