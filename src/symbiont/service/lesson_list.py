"""`symbiont lessons`: every active lesson of a repository, mined or written, with its source."""

from dataclasses import dataclass

from symbiont.core.notes import happened
from symbiont.miner.lesson_context import AuthoredLesson, LessonContext
from symbiont.miner.trained import lesson_id
from symbiont.service.effective_context import effective_contexts
from symbiont.store.local import Store

MINED = "mined"
REFLECTION = "reflection"
ADDED = "added"
TITLE_CHARS = 90
REFLECTION_LABEL = "from reflection"


@dataclass(frozen=True)
class LessonLine:
    """One lesson as listed: its id, where it came from, what it says, whether it is dismissed."""

    ident: str
    source: str
    text: str
    dismissed: bool
    has_words: bool


def source_of(item: AuthoredLesson) -> str:
    """`reflection` for a lesson written at session end, `added` for any other written one."""
    return REFLECTION if item.source_label.strip().lower() == REFLECTION_LABEL else ADDED


def lesson_lines(store: Store, project: str) -> list[LessonLine]:
    """Mined lessons, then written ones, in storage order."""
    words = effective_contexts(store, project)
    own = store.contexts.all(project)
    lines = [
        _line(lesson_id(lesson), MINED, happened(lesson.pain_point.signature), words, own)
        for lesson in store.lessons(project)
    ]
    lines += [
        _line(item.ident, source_of(item), item.text[:TITLE_CHARS], words, own)
        for item in store.curation.authored(project)
    ]
    return lines


def _line(
    ident: str,
    source: str,
    text: str,
    words: dict[str, LessonContext],
    own: dict[str, LessonContext],
) -> LessonLine:
    """A listed lesson; dismissed means the developer's choice or a verdict silences it."""
    said = words.get(ident)
    return LessonLine(ident, source, text, bool(said and said.intentional), ident in own)
