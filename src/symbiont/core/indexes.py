"""Incremental indexes over history: a decision costs its matches, not the size of history.

Violation prevented: **Computational Friction**. Counters, similarity and the
mushroom's recall each scanned all of history for every step; over thousands
of sessions that is quadratic, and the only answer left would have been a
bigger machine or fewer sessions (which changes what is measured). Indexes
keep the answers identical and the cost proportional to what matches.

An index is only a memo of a history that only ever grows: `sync(items)`
extends it with whatever is new when `items` continues what it already holds
(same first and last indexed element), and rebuilds from scratch otherwise.
It never decides anything; an index and a plain scan give the same answer
(the tests keep the scan as an oracle).
"""

import math
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

import numpy as np
import numpy.typing as npt

from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.records.schema import Record

_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class Bm25Shape:
    """The two BM25 tuning constants, named for what they control."""

    term_saturation: float
    length_normalisation: float


class _Collection(NamedTuple):
    """Statistics of the documents a BM25 query is scored over."""

    documents: int
    average_length: float


def continues(indexed: Sequence[object], items: Sequence[object]) -> bool:
    """True when `items` is what `indexed` holds plus (possibly) more."""
    if not indexed:
        return True
    held = len(indexed)
    return len(items) >= held and items[0] is indexed[0] and items[held - 1] is indexed[held - 1]


class Growing:
    """An append-only numpy array with amortized O(1) append."""

    def __init__(self, dtype: npt.DTypeLike) -> None:
        self._data = np.empty(16, dtype=dtype)
        self.size = 0

    def append(self, value: Any) -> None:
        """Add one value at the end, doubling capacity when full."""
        if self.size == len(self._data):
            self._data = np.resize(self._data, 2 * len(self._data))
        self._data[self.size] = value
        self.size += 1

    @property
    def view(self) -> np.ndarray:
        """The filled part of the array, without copying."""
        return self._data[: self.size]


class PainPointIndex:
    """Pain points by every element of their signature key, and failed ones by command.

    Elements are files, commands and error names; failed commands are also
    keyed by the normalized command.
    """

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._items: list[PainPoint] = []
        self._by_element: dict[str, list[int]] = defaultdict(list)
        self._by_command: dict[tuple[str, ...], list[int]] = defaultdict(list)
        self._by_signature: dict[Signature, list[int]] = defaultdict(list)

    def sync(self, points: Sequence[PainPoint]) -> None:
        """Index whatever `points` adds; rebuild if it does not continue the indexed history."""
        if not continues(self._items, points):
            self._reset()
        for pos in range(len(self._items), len(points)):
            self._add(pos, points[pos])

    def _add(self, pos: int, point: PainPoint) -> None:
        self._items.append(point)
        self._by_signature[point.signature].append(pos)
        for element in set(point.signature.key):
            self._by_element[element].append(pos)
        if point.signature.signal == Signal.FAILED_COMMAND:
            self._by_command[point.signature.key[:2]].append(pos)

    def matching(self, files: Sequence[str], command: tuple[str, ...] | None) -> list[PainPoint]:
        """Points naming one of `files` in their key, or failing the same `command`.

        Returned in the order they were added.
        """
        found: set[int] = set()
        for path in files:
            found.update(self._by_element.get(path, ()))
        if command is not None:
            found.update(self._by_command.get(command, ()))
        return [self._items[i] for i in sorted(found)]

    def with_signature(self, signature: Signature) -> list[PainPoint]:
        """Points with exactly this signature, in the order they were added."""
        return [self._items[i] for i in self._by_signature.get(signature, ())]

    def __len__(self) -> int:
        """Number of indexed points."""
        return len(self._items)


def tokens(record: Record) -> list[str]:
    """Lower-case words of a record's command and file names."""
    text = " ".join([record.command or "", *record.files])
    return [t.lower() for t in _WORD.findall(text)]


class TokenIndex:
    """Inverted index of records by the words in their command and files.

    Postings are numpy arrays (document positions, term counts) so a whole
    posting list is scored at once.
    """

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._items: list[Record] = []
        self._postings: dict[str, tuple[Growing, Growing]] = {}
        self._doc_terms: list[frozenset[str]] = []
        self._lengths = Growing(np.int64)
        self._by_session: dict[str, list[int]] = defaultdict(list)
        self.total_length = 0

    def sync(self, records: Sequence[Record]) -> None:
        """Index whatever `records` adds; rebuild if it does not continue the indexed history."""
        if not continues(self._items, records):
            self._reset()
        for pos in range(len(self._items), len(records)):
            self._add(pos, records[pos])

    def _add(self, pos: int, record: Record) -> None:
        words = tokens(record)
        self._items.append(record)
        self._lengths.append(len(words))
        self.total_length += len(words)
        self._by_session[record.session_id].append(pos)
        counts: dict[str, int] = defaultdict(int)
        for w in words:
            counts[w] += 1
        self._doc_terms.append(frozenset(counts))
        for term, tf in counts.items():
            where, how_many = self._postings.setdefault(
                term, (Growing(np.int32), Growing(np.int32))
            )
            where.append(pos)
            how_many.append(tf)

    def __len__(self) -> int:
        """Number of indexed records."""
        return len(self._items)

    def record(self, pos: int) -> Record:
        """The record indexed at position `pos`."""
        return self._items[pos]

    def not_before(self, current: Record) -> list[int]:
        """Positions of records that are not the past of `current`.

        That is its own session at or after its step (other sessions are all
        earlier work).
        """
        return [
            p
            for p in self._by_session.get(current.session_id, ())
            if self._items[p].step >= current.step
        ]

    def sharing_a_word(self, query: set[str]) -> np.ndarray:
        """Boolean mask over all positions: records with at least one query word."""
        mask = np.zeros(len(self._items), dtype=bool)
        for term in query:
            if term in self._postings:
                mask[self._postings[term][0].view] = True
        return mask

    def bm25_top(
        self, query: set[str], excluded: Sequence[int], size: int, shape: Bm25Shape
    ) -> list[int]:
        """Positions of the `size` best documents by BM25 (best first, ties to the earlier).

        Ranked among all but `excluded`, with the collection statistics taken
        over that remainder. Terms are added in sorted order so the arithmetic
        is the same however the query set iterates.
        """
        remaining = len(self._items) - len(excluded)
        if remaining <= 0:
            return []
        collection = _Collection(remaining, self._average_length(excluded, remaining))
        scores = np.zeros(len(self._items))
        for term in sorted(query & self._postings.keys()):
            contribution = self._term_contribution(term, excluded, collection, shape)
            if contribution is not None:
                positions, gain = contribution
                scores[positions] += gain
        if len(excluded):
            scores[list(excluded)] = 0.0
        return best_first(scores, size)

    def _average_length(self, excluded: Sequence[int], remaining: int) -> float:
        lengths = self._lengths.view
        kept = self.total_length - sum(int(lengths[pos]) for pos in excluded)
        return (kept / remaining) or 1.0

    def _term_contribution(
        self, term: str, excluded: Sequence[int], collection: _Collection, shape: Bm25Shape
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """(positions, score gain) for one query term, or None when no kept document has it."""
        where, how_many = self._postings[term]
        holding = where.size - sum(term in self._doc_terms[pos] for pos in excluded)
        if holding <= 0:
            return None
        idf = math.log(1 + (collection.documents - holding + 0.5) / (holding + 0.5))
        positions, tf = where.view, how_many.view.astype(np.float64)
        saturation, normalization = shape.term_saturation, shape.length_normalisation
        lengths = self._lengths.view[positions]
        gain = (
            idf
            * tf
            * (saturation + 1)
            / (
                tf
                + saturation
                * (1 - normalization + normalization * lengths / collection.average_length)
            )
        )
        return positions, gain


def best_first(scores: np.ndarray, size: int) -> list[int]:
    """Positions of the `size` highest positive scores; equal scores go to the earlier position."""
    positive = np.flatnonzero(scores > 0)
    if len(positive) == 0:
        return []
    values = scores[positive]
    if len(positive) > size:
        cutoff = np.partition(values, -size)[-size]
        keep = values >= cutoff
        positive, values = positive[keep], values[keep]
    order = np.lexsort((positive, -values))
    return [int(positive[i]) for i in order[:size]]


class InputMemo:
    """A boolean mask per input vector, remembered for one owner object (such as a wiring).

    Meta-training asks a filler for the same step's cells thousands of times. The memo keeps
    the active positions only and forgets everything when the owner changes.
    """

    def __init__(self) -> None:
        self._owner: object | None = None
        self._found: dict[bytes, tuple[int, np.ndarray]] = {}

    def lookup(self, x: np.ndarray, owner: object, compute: Callable[[], np.ndarray]) -> np.ndarray:
        """The mask `compute()` gives for `x` under `owner`, computed once."""
        if self._owner is not owner:
            self._owner, self._found = owner, {}
        key = np.asarray(x, dtype=np.float64).tobytes()
        if key not in self._found:
            mask = compute()
            self._found[key] = (len(mask), np.flatnonzero(mask))
        size, positions = self._found[key]
        result = np.zeros(size, dtype=bool)
        result[positions] = True
        return result
