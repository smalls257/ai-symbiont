"""Mining: re-read a project's history from the harness's own logs and keep only lessons.

Records live for one call: read through their readers, mined, turned into lessons and dropped. The
hold-out check runs here, before a lesson is stored. A new log is registered only when mining with
it succeeds; a registered log that went missing or no longer parses raises naming the file.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from symbiont.miner.churn import churn
from symbiont.miner.lessons import Lesson, lessons_from, resolution_coverage
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.screen import ScreenRules, screen
from symbiont.readers import Reader
from symbiont.records.holdout import refuse_held_out
from symbiont.records.schema import Record
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store
from symbiont.store.settings import read_mining_settings


class UnknownReaderError(ValueError):
    """A source names a reader that is not installed."""

    def __init__(self, reader: str, known: Iterable[str]):
        """Name the reader and the known ones."""
        super().__init__(f"no reader called {reader!r}; known readers: {', '.join(sorted(known))}")
        self.reader = reader


@dataclass(frozen=True)
class MiningRules:
    """How a project is mined: the readers by name, the held-out tasks, the blast-radius map."""

    readers: Mapping[str, Reader]
    held_out_tasks: frozenset[str]
    # references[path] = files that import or name `path`; {} when there is no checkout.
    references: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Which groups become lessons; `screen_rules_from` builds it from the developer's settings.
    screen: ScreenRules = field(default_factory=ScreenRules)
    # Directory names the repository goes by, for churn's repo-relative paths (the project's own
    # name is always added).
    repo_names: frozenset[str] = frozenset()


def screen_rules_from(data_dir: Path) -> ScreenRules:
    """The screening rules the developer's mining settings ask for."""
    return ScreenRules(min_sessions=read_mining_settings(data_dir).min_sessions)


def with_ignored(rules: MiningRules, store: Store, project: str) -> MiningRules:
    """`rules` plus the patterns the developer set aside in `project`, so mining holds them back."""
    ignored = rules.screen.ignored | store.ignored.signatures(project)
    return replace(rules, screen=replace(rules.screen, ignored=ignored))


def mined_outcome(records: Sequence[Record], rules: MiningRules, project: str) -> MiningOutcome:
    """Mine `records`, keep the lessons with a shown fix, count the rest, measure file churn."""
    sessions = sessions_of(records)
    names = rules.repo_names | {project}
    lessons = lessons_from(mine_history(sessions, rules.references), records, names)
    screened = screen(lessons, rules.screen)
    return MiningOutcome(screened.kept, screened.held, screened.struggle, churn(sessions, names))


def remine(
    store: Store, project: str, rules: MiningRules, *, adding: Iterable[Source] = ()
) -> list[Lesson]:
    """Re-read every source of `project` plus `adding` and replace its lessons.

    Raises HoldOutViolationError (nothing stored) for a held-out record; UnknownReaderError,
    ReadError or OSError when a source cannot be read.
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
    outcome = mined_outcome(records, with_ignored(rules, store, project), project)
    store.mined.save(project, list(new), outcome, held_out_tasks=rules.held_out_tasks)
    return outcome.kept


def mine_sources(
    sources: Sequence[Source], rules: MiningRules, on_read: Callable[[list[Lesson]], None]
) -> MiningOutcome:
    """Mine `sources` with no store; `on_read` gets each log's lessons (alone) as a live preview.

    The previews are unscreened (the progress count); the result mines all logs together and
    screens them. Raises HoldOutViolationError, UnknownReaderError, ReadError or OSError.
    """
    records: list[Record] = []
    for source in sources:
        read = read_source(source, rules.readers)
        records += read
        on_read(lessons_from(mine_history(sessions_of(read), rules.references), read))
    refuse_held_out(records, rules.held_out_tasks)
    return mined_outcome(records, rules, sources[0].project if sources else "")


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
