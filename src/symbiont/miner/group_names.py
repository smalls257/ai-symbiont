"""The heading an Inbox group has until the developer renames it.

A failure group is "<program> failing with <what broke, in plain words>", so two groups of one
program with different errors never read alike. A correction group is what the session model
called it. Pure: text in, text out.
"""

from collections import Counter
from collections.abc import Sequence

from symbiont.miner.failure_keys import broke_in_words
from symbiont.miner.incident_groups import IncidentGroup
from symbiont.miner.incident_types import Incident
from symbiont.miner.incident_words import without_cd
from symbiont.miner.painpoint import Signal

NO_PROGRAM = ("", "-")  # a failure whose command line named no program is keyed "-"
NAME_CHARS = 80  # the most a group name may hold (POST /triage refuses longer)


def generated_name(group: IncidentGroup) -> str:
    """The heading of `group`, at most NAME_CHARS long."""
    newest = group.cards[0]
    if group.signal is Signal.CORRECTION:
        return shortened(group.model_name or newest.what_happened)
    program = group.trigger.program if group.trigger else newest.situation[1]
    if program in NO_PROGRAM:
        return shortened(newest.what_happened)
    broke = _broke_of(newest)
    if broke:
        return shortened(f"{program} failing with {broke_in_words(broke)}")
    command = without_cd(newest.example).removeprefix(program).strip()
    return shortened(f"{program} failing: {command}" if command else f"{program} failing")


def distinct(names: Sequence[str], places: Sequence[str]) -> list[str]:
    """`names` with a repeat told apart by its place (a directory) or, failing that, a number."""
    seen: Counter[str] = Counter()
    repeated = {name for name, count in Counter(names).items() if count > 1}
    out = []
    for name, place in zip(names, places, strict=True):
        if name not in repeated:
            out.append(name)
            continue
        seen[name] += 1
        out.append(_suffixed(name, f" on {place}" if place else f" ({seen[name]})"))
    return out if len(set(out)) == len(out) else _numbered(out)


def _numbered(names: Sequence[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for name in names:
        seen[name] += 1
        out.append(name if seen[name] == 1 else _suffixed(name, f" ({seen[name]})"))
    return out


def _suffixed(name: str, suffix: str) -> str:
    """`name` + `suffix` within NAME_CHARS: the name gives way, so the suffix is never cut off."""
    room = NAME_CHARS - len(suffix)
    stem = name if len(name) <= room else name[: room - 1] + "\u2026"
    return stem + suffix


def shortened(text: str) -> str:
    """`text` on one line, at most NAME_CHARS characters, ending in an ellipsis when cut."""
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= NAME_CHARS else one_line[: NAME_CHARS - 1] + "…"


def _broke_of(card: Incident) -> str:
    kind, _, rest = card.fingerprint.partition(":")
    return rest.partition(":")[2] if kind == "failure" else ""
