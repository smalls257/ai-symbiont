"""Review lessons for tests: a comment a reviewer made and a later edit answered."""

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature


def flag(session, step, gist, path="src/batch.ts", reviewer="CodeRabbit", fixed="batch.ts"):
    key = (path, reviewer, gist)
    pain = PainPoint(Signature(Signal.REVIEW_FLAG, key), session, step, ((session, step),))
    phrase = (f"edited {fixed}",) if fixed else ()
    return Lesson(
        pain_point=pain,
        quote="",
        resolution=phrase,
        unresolved_because=None,
        remote_safe=True,
        sources=((session, step),),
    )


NULLS = [
    flag("s1", 3, "Possible null dereference when the batch is empty"),
    flag("s2", 4, "Empty batch causes a null dereference", path="src/queue.ts", reviewer="Copilot"),
]
OTHER = flag("s3", 1, "Rename the retry timeout constant", path="src/retry.ts", fixed="retry.ts")
