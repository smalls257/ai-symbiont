"""The sentence the page shows when mining kept no lesson, taken from the main reason for holding.

"Nothing repeated enough" would send the developer to a setting that cannot help when the real
reason is that no fix was ever shown, so the sentence names the rule.
"""

from collections.abc import Mapping

from symbiont.miner.screen import HoldReason
from symbiont.service.wording import counted
from symbiont.store.held_back import REASON_WORDS

THE_RULE = (
    "a lesson needs a fix shown in the same session: a code edit, or a command corrected "
    "after a wrong invocation"
)


def no_lessons_sentence(held: Mapping[HoldReason, int], min_sessions: int) -> str:
    """Why no lesson was formed, from the main reason groups were held back."""
    counts = {reason: n for reason, n in held.items() if n and reason is not HoldReason.IGNORED}
    if not counts:
        if held.get(HoldReason.IGNORED):
            return "No lesson is active: every lesson was set aside by you. Restore one to use it."
        return f"No lesson yet: {THE_RULE}, and no failure in this history showed one."
    main = max(HoldReason, key=lambda reason: counts.get(reason, 0))
    total = sum(counts.values())
    if main is HoldReason.NO_FIX_SHOWN:
        return (
            f"No lesson yet: {THE_RULE}. {counts[main]} of {counted(total, 'group')} of failures "
            "never showed one (see Held back). The min_sessions setting only moves the groups "
            "held for too few sessions."
        )
    if main is HoldReason.TOO_FEW_SESSIONS:
        return (
            f"No lesson yet: every failure with a fix shown came back in fewer than "
            f"{counted(min_sessions, 'session')}. Run `symbiont settings mining min_sessions 1` "
            "and mine again to teach single-session traps."
        )
    why = REASON_WORDS[main]
    return f"No lesson yet: {counts[main]} of {counted(total, 'group')} held back as {why}."
