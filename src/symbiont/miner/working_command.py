"""The command an agent ran, as the one short line a person recognizes it by.

An example line on the Inbox shows the working command: not the `cd dir` before it, the heredoc
a commit message was fed through, the message itself, a redirection or a filter pipe at the end.
Pure: text in, text out.
"""

import re

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.read_only import OUTPUT_FILTERS, SHELL_PLUMBING
from symbiont.miner.shell_text import shell_text
from symbiont.miner.shown_paths import plain_paths

# One line of an Inbox row; longer and the row wraps into a wall of text.
LINE_CHARS = 100
_MESSAGE = re.compile(
    r"(?P<flag>(?:-m|--message)(?:\s+|=))"
    r"(?:\"\$\(.*|\"(?:[^\"\\]|\\.)*\"|'[^']*')",
    re.S,
)
_REDIRECTION = re.compile(r"\s+(?:\d*|&)>>?(?:&\d+|\s*[^\s|;&]+)")
_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
_CUT = "…"


def working_command(command: str, repo_names: frozenset[str] = frozenset()) -> str:
    """The working command on one line, at most LINE_CHARS, paths shortened and secrets scrubbed."""
    bare = _MESSAGE.sub(lambda found: found["flag"].rstrip("= ") + " " + _CUT, command)
    line = _without_noise(_working_segment(shell_text(bare)))
    line = plain_paths(scrub(line), repo_names)
    return line if len(line) <= LINE_CHARS else line[: LINE_CHARS - 1].rstrip() + _CUT


def _working_segment(text: str) -> str:
    """The segment a failure is about: the last `;` list that does work, its first working step.

    The same rule as `failing_program`: in `git add x && git commit` the step that can fail
    first is `git add`, and `cd dir &&` is setup, never the command.
    """
    lists = [_top_level_split(part, ("&&", "||")) for part in _top_level_split(text, (";",))]
    working = [[seg for seg in chain if _does_work(seg)] for chain in lists]
    chains = [chain for chain in working if chain]
    return chains[-1][0] if chains else _any_segment(lists)


def _any_segment(lists: list[list[str]]) -> str:
    """The first non-empty segment, for a line made only of setup."""
    return next((seg for chain in lists for seg in chain if seg), "")


def _does_work(segment: str) -> bool:
    return bool(segment.split()) and segment.split()[0] not in SHELL_PLUMBING


def _without_noise(segment: str) -> str:
    """The segment without redirections and without trailing pipes into output filters."""
    stages = [_without_redirections(stage) for stage in _top_level_split(segment, ("|",))]
    stages = [stage for stage in stages if stage]
    while len(stages) > 1 and stages[-1].split()[0] in OUTPUT_FILTERS:
        stages.pop()
    return " | ".join(stages)


def _without_redirections(stage: str) -> str:
    """The stage without `2>&1`, `> file` and the like; a `>` inside quotes is not one."""
    quoted: list[str] = []

    def hide(found: re.Match[str]) -> str:
        quoted.append(found.group(0))
        return f"\x00{len(quoted) - 1}\x00"

    masked = _QUOTED.sub(hide, stage)
    bare = _REDIRECTION.sub("", masked).strip()
    return re.sub(r"\x00(\d+)\x00", lambda found: quoted[int(found.group(1))], bare)


def _top_level_split(text: str, separators: tuple[str, ...]) -> list[str]:
    """`text` cut at the separators that sit outside quotes; a single `|` is not part of `||`."""
    parts, current, quote, pos = [], "", "", 0
    while pos < len(text):
        char = text[pos]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        else:
            found = _separator_at(text, pos, separators)
            if found:
                parts.append(current.strip())
                current, pos = "", pos + len(found)
                continue
        current += char
        pos += 1
    return [*parts, current.strip()]


def _separator_at(text: str, index: int, separators: tuple[str, ...]) -> str:
    for separator in sorted(separators, key=len, reverse=True):
        if text.startswith(separator, index) and not _inside_longer(text, index, separator):
            return separator
    return ""


def _inside_longer(text: str, index: int, separator: str) -> bool:
    """A lone `|` that is half of `||` must not split twice."""
    return separator == "|" and (text[index : index + 2] == "||" or text[index - 1 : index] == "|")
