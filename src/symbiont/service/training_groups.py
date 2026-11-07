"""Which incident groups feed nightly training: the failed commands whose lesson the screen keeps.

Why: the Teach dialog must not promise that a note trains the adapter when the mined lesson behind
the group was held back (one session, no fix, a probe) or never had a fix command to judge.
Nightly reads the same lessons, through `stale_lessons.screened_now` and `judgeable`.
"""

from symbiont.core.judge_format import judgeable
from symbiont.miner.screen import ScreenRules
from symbiont.service.stale_lessons import screened_now
from symbiont.store.local import Store


def trained_fingerprints(store: Store, project: str, rules: ScreenRules) -> frozenset[str]:
    """The group keys (`failure:<program>:<what broke>`) of the lessons nightly would train on."""
    kept = screened_now(store, project, store.lessons(project), rules)
    return frozenset(
        f"failure:{signature.key[0]}:{signature.key[-1]}"
        for lesson in kept
        if judgeable(lesson, project) is not None
        for signature in [lesson.pain_point.signature]
    )
