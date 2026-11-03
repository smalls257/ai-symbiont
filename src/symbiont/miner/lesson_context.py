"""What the developer said about a lesson, in their own words."""

from dataclasses import dataclass
from enum import StrEnum


class Priority(StrEnum):
    """How much the developer cares that this lesson is heard."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class AppliesTo:
    """Where a rule applies, as the writer tagged it: domain terms and path prefixes."""

    terms: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()


@dataclass(frozen=True)
class LessonContext:
    """The developer's words for a lesson; `intentional` says the failure is on purpose."""

    text: str
    intentional: bool = False
    priority: Priority = Priority.NORMAL
    applies: AppliesTo = AppliesTo()


class ReviewOverride(StrEnum):
    """The developer's answer to a reviewer's silencing verdict; it outranks the verdict."""

    KEEP = "keep"
    DISMISS = "dismiss"


class LessonKind(StrEnum):
    """What a lesson written by the session's model (or the developer) is."""

    MISTAKE = "mistake"
    RULE = "rule"
    FRICTION = "friction"
    CORRECTION = "correction"


class Severity(StrEnum):
    """How much a written lesson matters; it becomes the lesson's priority."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verdict(StrEnum):
    """The model's (or developer's) judgment of a rule-found pain point."""

    MISTAKE = "mistake"
    EXPECTED = "expected"
    NOISE = "noise"


@dataclass(frozen=True)
class AuthoredLesson:
    """A lesson written in plain words rather than mined from a record."""

    ident: str
    text: str
    kind: LessonKind
    files: tuple[str, ...] = ()
    source_label: str = ""
    severity: Severity = Severity.MEDIUM
    applies: AppliesTo = AppliesTo()
    # Where the lesson was learned (a pull request's address), so the developer can audit it.
    source_url: str = ""
    # The reviewer's own words that state the rule, as the model supplied them (symbiont never
    # sees the review text, so it cannot check them); empty for a lesson with no quote.
    quote: str = ""
    quote_role: str = ""


@dataclass(frozen=True)
class Review:
    """A verdict on a mined pain point; expected and noise silence its note."""

    verdict: Verdict
    rule: str = ""
    title: str = ""
    merge_with: str | None = None
    applies: AppliesTo = AppliesTo()
