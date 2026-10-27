"""Route B training data: what a personal LoRA on Glimmer learns from history.

Route B teaches the model itself the pain points the MCP route would surface:
to recall them (`recall_pairs`) and to make the correction unprompted
(`correction_pairs`). The unit exists to prevent a Silent Fallback: a made-up
target. Every completion is quoted from the original records (a summary would
teach the model our paraphrase, not what happened), and when the history holds
no correction for a pain point the derivation is empty with a stated reason.

Pure: records in, examples out. No network, no clock, no files.

Not mistakes, so never examples (same rule every learner reads history by,
`core.features.meaningful_history`): breakage of a hub module, and rework of a
file the session made for itself.

`records` must hold the pain point's whole chain in the order it ran, since a
reworked edit's surviving version may sit in a later session.
"""

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from functools import partial

from symbiont.core.features import meaningful_history, scratch_files
from symbiont.core.slot import Situation
from symbiont.miner.painpoint import PainPoint, RecordRef, Signal, Signature
from symbiont.records.holdout import HoldOutViolationError, normalise_task_id
from symbiont.records.schema import Record
from symbiont.routeb.signal_texts import CORRECTION_BY_SIGNAL, RECALL_BY_SIGNAL, quote_record

DEFAULT_MAX_QUOTE_CHARS = 2000


@dataclass(frozen=True)
class Example:
    """One training pair, with the records its text was quoted from."""

    kind: str  # "recall" or "correction"
    prompt: str
    completion: str
    sources: tuple[RecordRef, ...]
    signature: Signature
    # False if any source record is private: such an example must not reach Spark.
    spark_safe: bool


@dataclass(frozen=True)
class DatasetLimits:
    """What bounds a dataset: the pre-registered cut-off, the hold-out and the quote size."""

    top_n: int
    held_out_tasks: Collection[str]
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS


@dataclass(frozen=True)
class Derivation:
    """Examples for one pain point, or none and the reason why."""

    examples: tuple[Example, ...]
    reason: str | None

    def __post_init__(self) -> None:
        """Refuse an empty derivation that does not say why."""
        if not self.examples and not self.reason:
            raise ValueError("a derivation with no examples needs a reason")


@dataclass(frozen=True)
class Dataset:
    """The examples kept, the pain points behind them, and what was left out and why."""

    examples: tuple[Example, ...]
    pain_points: tuple[PainPoint, ...]  # the ones kept
    dropped: dict[str, int]  # reason -> pain points left out
    skipped: tuple[str, ...]  # "recall: ..." / "correction: ..." derivations that came up empty


# --- public derivations -------------------------------------------------------


def recall_pairs(
    pp: PainPoint,
    records: Sequence[Record],
    *,
    hubs: frozenset[str] = frozenset(),
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
) -> Derivation:
    """Self-study Q&A: 'What broke last time I touched X?' answered with original text.

    The answer is the original text of the cited records.
    """
    cited, why_not = _usable(pp, records, hubs)
    if cited is None:
        return _none(why_not)
    quote = partial(quote_record, limit=max_quote_chars)
    question, answer = RECALL_BY_SIGNAL[pp.signature.signal](pp, cited, quote)
    return _one("recall", question, answer, pp, cited)


def correction_pairs(
    pp: PainPoint,
    records: Sequence[Record],
    *,
    hubs: frozenset[str] = frozenset(),
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
) -> Derivation:
    """Situation -> the corrected action the history actually shows."""
    cited, why_not = _usable(pp, records, hubs)
    if cited is None:
        return _none(why_not)
    quote = partial(quote_record, limit=max_quote_chars)
    found = CORRECTION_BY_SIGNAL[pp.signature.signal](pp, cited, records, quote)
    if isinstance(found, str):
        return _none(found)
    situation, target, used = found
    return _one("correction", situation, target, pp, used)


def build_dataset(
    pain_points: Iterable[PainPoint],
    records: Sequence[Record],
    limits: DatasetLimits,
    *,
    hubs: frozenset[str] = frozenset(),
) -> Dataset:
    """Examples for the `limits.top_n` most recurrent kinds of trouble.

    The cap is set by the pre-registration, not here. Rank is how many times
    the same signature occurred, ties by first appearance; every occurrence of
    a kept signature contributes. Held-out tasks are removed first, so they
    neither take a slot nor serve as a source; each omission is counted in
    `dropped`.
    """
    held = _held_out_sessions(records, limits.held_out_tasks)
    usable = [r for r in records if r.session_id not in held]
    dropped: Counter[str] = Counter()
    candidates = []
    for pp in pain_points:
        if _cites_session_in(pp, held):
            dropped["held-out task"] += 1
        elif why := _not_a_mistake(pp, usable, hubs):
            dropped[why] += 1
        else:
            candidates.append(pp)
    kept = _top_signatures(candidates, limits.top_n)
    dropped["beyond top-N"] += len(candidates) - len(kept)
    examples, skipped = _derive_all(kept, usable, hubs, limits.max_quote_chars)
    _assert_no_held_out_source(examples, held)
    return Dataset(tuple(examples), tuple(kept), dict(dropped), tuple(skipped))


# --- selection and hold-out ---------------------------------------------------


def _top_signatures(pain_points: list[PainPoint], top_n: int) -> list[PainPoint]:
    counts = Counter(p.signature for p in pain_points)
    first_seen = {sig: i for i, sig in reversed(list(enumerate(p.signature for p in pain_points)))}
    ranked = sorted(counts, key=lambda sig: (-counts[sig], first_seen[sig]))
    keep = set(ranked[:top_n])
    return [p for p in pain_points if p.signature in keep]


def _held_out_sessions(
    records: Sequence[Record], held_out_tasks: Collection[str]
) -> frozenset[str]:
    """Sessions of any held-out task.

    Ids are compared as the store does, so the two guards agree; an id in no
    benchmark spelling raises.
    """
    held = {normalise_task_id(t) for t in held_out_tasks}
    if not held:
        return frozenset()
    return frozenset(
        r.session_id
        for r in records
        if r.task_id is not None and normalise_task_id(r.task_id) in held
    )


def _cites_session_in(pp: PainPoint, sessions: frozenset[str]) -> bool:
    return pp.session_id in sessions or any(sid in sessions for sid, _ in pp.record_refs)


def _assert_no_held_out_source(examples: list[Example], held: frozenset[str]) -> None:
    for example in examples:
        for session_id, _ in example.sources:
            if session_id in held:
                raise HoldOutViolationError("(held-out task)", session_id)


def _derive_all(
    kept: list[PainPoint], records: Sequence[Record], hubs: frozenset[str], max_quote_chars: int
) -> tuple[list[Example], list[str]]:
    examples: dict[tuple[str, str, str], Example] = {}
    skipped = []
    for pp in kept:
        for name, derive in (("recall", recall_pairs), ("correction", correction_pairs)):
            got = derive(pp, records, hubs=hubs, max_quote_chars=max_quote_chars)
            if got.reason:
                skipped.append(f"{name}: {got.reason}")
            for e in got.examples:
                examples.setdefault((e.kind, e.prompt, e.completion), e)
    return list(examples.values()), skipped


# --- shared helpers -----------------------------------------------------------


def _none(reason: str | None) -> Derivation:
    return Derivation((), reason)


def _one(
    kind: str, prompt: str, completion: str, pp: PainPoint, used: Sequence[Record]
) -> Derivation:
    example = Example(
        kind=kind,
        prompt=prompt,
        completion=completion,
        sources=tuple((r.session_id, r.step) for r in used),
        signature=pp.signature,
        spark_safe=all(r.provenance.spark_safe for r in used),
    )
    return Derivation((example,), None)


def _usable(
    pp: PainPoint, records: Sequence[Record], hubs: frozenset[str]
) -> tuple[list[Record] | None, str | None]:
    """Return (cited records, None), or (None, why this pain point teaches nothing)."""
    if why := _not_a_mistake(pp, records, hubs):
        return None, why
    by_ref = {(r.session_id, r.step): r for r in records}
    for ref in pp.record_refs:
        if ref not in by_ref:
            return None, f"cited record {ref[0]}:{ref[1]} is not in the records"
    return [by_ref[ref] for ref in pp.record_refs], None


def _not_a_mistake(pp: PainPoint, records: Sequence[Record], hubs: frozenset[str]) -> str | None:
    empty = Situation(project="", session_prefix=(), history=(pp,), candidates=())
    if meaningful_history(empty, hubs, scratch_files(records)):
        return None
    if pp.signature.signal == Signal.BLAST_RADIUS:
        return f"breakage of hub module {pp.signature.key[-1]} says nothing about the edit"
    return f"rework of {pp.signature.key[0]}, a scratch file the session made for itself"
