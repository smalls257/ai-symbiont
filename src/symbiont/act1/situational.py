"""Situational lessons: advice tied to the situations it was mined from, shown only when one fits.

A lesson carries the observations where its mistake happened. At each decision the ranker scores
every lesson by how closely the current observation matches one of those; a cutoff decides whether
the model sees anything, so most moves get no lesson. Pure: text in, text out.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

MAX_SHOWN = 2  # the owner's cap: top one, at most two
HEADING = "Notes from earlier games that may fit this moment (use one only if it applies):"
WORD = re.compile(r"[A-Za-z][A-Za-z]+")


class NoLessonsError(ValueError):
    """A ranker was built from no lesson or from lessons with no example observation."""


@dataclass(frozen=True)
class SituationalLesson:
    """One piece of advice and the observations of the moments it was mined from."""

    advice: str
    examples: tuple[str, ...]


def words_of(observation: str) -> Counter[str]:
    """Lowercased words of an observation; numbers and distances are left out on purpose."""
    return Counter(word.lower() for word in WORD.findall(observation))


class Ranker:
    """Scores lessons against an observation by tf-idf cosine to their nearest example."""

    def __init__(self, lessons: Sequence[SituationalLesson]) -> None:
        """Raises NoLessonsError when there is nothing to rank."""
        if not lessons or any(not lesson.examples for lesson in lessons):
            raise NoLessonsError("every lesson needs at least one example observation")
        self.lessons = tuple(lessons)
        documents = [words_of(example) for lesson in lessons for example in lesson.examples]
        frequency = Counter(word for document in documents for word in document)
        self._idf = {w: math.log((1 + len(documents)) / (1 + n)) + 1 for w, n in frequency.items()}
        self._vectors = [[self._vector(words_of(e)) for e in lesson.examples] for lesson in lessons]

    def _vector(self, counts: Counter[str]) -> dict[str, float]:
        """A unit-length tf-idf vector; words never seen in an example carry no weight."""
        raw = {w: (1 + math.log(n)) * self._idf[w] for w, n in counts.items() if w in self._idf}
        norm = math.sqrt(sum(v * v for v in raw.values()))
        return {w: v / norm for w, v in raw.items()} if norm else {}

    def scores(self, observation: str) -> list[float]:
        """Each lesson's best cosine to the observation, in lesson order."""
        now = self._vector(words_of(observation))
        return [
            max(sum(now.get(w, 0.0) * v for w, v in example.items()) for example in examples)
            for examples in self._vectors
        ]

    def choose(self, observation: str, cutoff: float, limit: int = MAX_SHOWN) -> list[str]:
        """Advice of up to `limit` lessons scoring at least the cutoff, best first, no repeats."""
        scored = sorted(zip(self.scores(observation), self.lessons, strict=True), key=_by_score)
        shown: list[str] = []
        for score, lesson in scored:
            if score < cutoff or len(shown) == limit:
                break
            if lesson.advice not in shown:
                shown.append(lesson.advice)
        return shown


def _by_score(pair: tuple[float, SituationalLesson]) -> float:
    """Sort key: highest score first."""
    return -pair[0]


def render_lessons(advice: Sequence[str]) -> str:
    """The block put before the observation, or an empty string when nothing is shown."""
    if not advice:
        return ""
    return HEADING + "\n" + "\n".join(f"- {line}" for line in advice)


def cutoff_for_show_rate(best_scores: Sequence[float], rate: float) -> float:
    """The cutoff under which about `rate` of the given top scores would show a lesson.

    Raises ValueError for a rate outside 0 to 1 or for no scores.
    """
    if not best_scores or not 0 < rate < 1:
        raise ValueError(f"need scores and a rate between 0 and 1, got {len(best_scores)}, {rate}")
    ordered = sorted(best_scores)
    return ordered[min(len(ordered) - 1, int(len(ordered) * (1 - rate)))]
