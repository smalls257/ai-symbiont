"""Mining: re-read a project's history from the harness's own logs and keep only lessons.

Records live only for the length of one call: every registered log is read
through its reader, mined as one history, turned into lessons that carry their
own quote and privacy flag, and dropped. The hold-out check runs here, before a
lesson is stored, because no record is kept to check later.

A new log is registered only when the mining that includes it succeeds, so a
held-out or unreadable log never becomes a source that blocks every later run.
A registered log that has gone missing or no longer parses raises naming the
file: mining around it would silently drop that history.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from symbiont.miner.lessons import Lesson, lessons_from, resolution_coverage
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.readers import Reader
from symbiont.records.holdout import refuse_held_out
from symbiont.records.schema import Record
from symbiont.store.local import Source, Store


class UnknownReaderError(ValueError):
    """A source names a reader that is not installed."""

    def __init__(self, reader: str, known: Iterable[str]):
        super().__init__(f"no reader called {reader!r}; known readers: {', '.join(sorted(known))}")
        self.reader = reader


@dataclass(frozen=True)
class MiningRules:
    """How a project is mined: the readers by name, the held-out tasks, the blast-radius map."""

    readers: Mapping[str, Reader]
    held_out_tasks: frozenset[str]
    # references[path] = files that import or name `path`; {} when there is no checkout.
    references: Mapping[str, frozenset[str]] = field(default_factory=dict)


def remine(
    store: Store, project: str, rules: MiningRules, *, adding: Iterable[Source] = ()
) -> list[Lesson]:
    """Re-read every source of `project` plus `adding`, and replace its lessons.

    Raises HoldOutViolationError (nothing is stored or registered) when any
    record belongs to a held-out task; UnknownReaderError, ReadError or OSError
    when a source cannot be read.
    """
    known = store.sources(project)
    new = [s for s in dict.fromkeys(adding) if s not in known]
    return remine_with_read(store, project, rules, {s: read_source(s, rules.readers) for s in new})


def remine_with_read(
    store: Store, project: str, rules: MiningRules, new: Mapping[Source, list[Record]]
) -> list[Lesson]:
    """As `remine`, for new sources the caller has already read (so no log is read twice)."""
    known = [s for s in store.sources(project) if s not in new]
    records = [r for source in known for r in read_source(source, rules.readers)]
    records += [r for read in new.values() for r in read]
    refuse_held_out(records, rules.held_out_tasks)
    lessons = lessons_from(mine_history(sessions_of(records), rules.references), records)
    store.save_mining(project, list(new), lessons, held_out_tasks=rules.held_out_tasks)
    return lessons


def read_source(source: Source, readers: Mapping[str, Reader]) -> list[Record]:
    """Every record in one harness log, read fresh."""
    reader = readers.get(source.reader)
    if reader is None:
        raise UnknownReaderError(source.reader, readers)
    return list(reader(Path(source.path), source.project))


def coverage_lines(lessons: Iterable[Lesson]) -> list[str]:
    """One line per signal: how many of its lessons have a resolution found. Counts only."""
    return [
        f"{signal.value}: {counted.resolved} of {counted.total} resolved"
        for signal, counted in resolution_coverage(lessons).items()
    ]
