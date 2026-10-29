"""One round of the recursive loop: attempt, verify, harvest, lesson utility, train, evaluate.

Domain questions go to the `Domain` plugin, what gets trained to the route's `Learner`. Each step
prints one line of counts, and the round's ledger entry keeps per-step counts, the per-lesson
utility table and the training manifest. The hold-out is checked first every round, and a
lesson text that leaks a held-out answer stops the round before anything is trained.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

from attempts import (
    Attempt,
    HeldOutMiningError,
    refuse_baseline_tasks,
    training_only,
    verified,
)
from card_rows import card_rows, verify_questions
from domain import Domain, Harvest, LessonLeakError
from learners import Learner, LearnJob
from ledger import Ledger
from loop_cards import LessonCard
from training_plan import PlanInputs, PreviousTraining, Row, TrainMode, plan_training, row_key
from utility import (
    Decision,
    LessonRecord,
    LessonUtility,
    harvest_quotas,
    in_baseline,
    judge_lessons,
    kind_scores,
)

DEFAULT_QUOTA = 6  # new lessons per harvest kind per round before any kind has been judged


@dataclass(frozen=True)
class LoopSettings:
    """The loop's knobs; the defaults are the honest-evaluation choices."""

    train_mode: TrainMode = TrainMode.FROM_SCRATCH
    base_quota: int = DEFAULT_QUOTA


@dataclass
class RoundContext:
    """What one round runs against."""

    domain: Domain
    learner: Learner
    ledger: Ledger
    settings: LoopSettings
    say: Callable[[str], None] = print


def run_round(ctx: RoundContext) -> dict:
    """Run the next round end to end; returns (and appends to the ledger) its entry."""
    domain, ledger = ctx.domain, ctx.ledger
    held_out = domain.held_out()
    ledger.require_held_out(held_out)
    index = ledger.next_round
    served, trained = ledger.current(ctx.learner.base())
    graded = _attempt_and_verify(ctx, index, served, trained)
    harvest = _harvest(ctx)
    table = _utility(ctx, served, graded)
    plan_entry = _train(ctx, index, harvest, table)
    entry = {
        "round": index,
        "model_in": served,
        "attempts": _counts(graded),
        "harvest": _harvest_counts(harvest),
        "utility": [_table_row(row) for row in table],
        **plan_entry,
    }
    entry["eval"] = _evaluate(ctx, index, entry["model_out"], frozenset(entry["trained_lessons"]))
    ledger.rounds.append(entry)
    for lesson_id in entry["trained_lessons"]:
        ledger.rounds_trained[lesson_id] = ledger.rounds_trained.get(lesson_id, 0) + 1
    return entry


def _attempt_and_verify(
    ctx: RoundContext, index: int, served: str, trained: frozenset[str]
) -> list[Attempt]:
    held_out = ctx.domain.held_out()
    tasks = ctx.domain.training_batch(index)
    if set(tasks) & held_out:
        raise HeldOutMiningError(f"training batch names held-out tasks: {set(tasks) & held_out}")
    attempts = ctx.domain.attempt(served, tasks, index, trained)
    ctx.say(f"[1/6] attempt: {served} on {len(tasks)} training tasks, {len(attempts)} attempts")
    batch = verified(attempts)
    graded = training_only(batch.graded, held_out)
    ctx.ledger.attempts.extend(graded)
    ctx.say(
        f"[2/6] verify: {len(batch.passed)} passed, {len(graded) - len(batch.passed)} failed, "
        f"{batch.ungraded} ungraded (not mined)"
    )
    return graded


def _harvest(ctx: RoundContext) -> Harvest:
    """Cards from the mined half of every graded training attempt; new ids per kind capped."""
    ledger = ctx.ledger
    scores = ledger.rounds[-1]["kind_scores"] if ledger.rounds else {}
    kinds = {card.kind for card in ledger.cards.values()} | set(scores)
    quotas = harvest_quotas(scores, kinds, ctx.settings.base_quota)
    live = {k: c for k, c in ledger.cards.items() if k not in ledger.retired}
    mined = [a for a in ledger.attempts if not in_baseline(a.task_id)]
    harvest = ctx.domain.harvest(mined, live, quotas)
    for card in harvest.cards:
        refuse_baseline_tasks(card.source_tasks, f"card {card.lesson_id}")
    added = _admit(ledger, harvest.cards, quotas, ctx.settings.base_quota)
    _refuse_leaks(ctx.domain, harvest, ledger.cards)
    ctx.say(
        f"[3/6] harvest: {added} new cards, {len(live)} kept before, "
        f"{sum(c.is_open for c in ledger.cards.values())} open, {harvest.unresolved} unresolved"
    )
    return harvest


def _admit(
    ledger: Ledger, cards: Sequence[LessonCard], quotas: Mapping[str, int], base: int
) -> int:
    """Update known cards; add new ones up to their kind's quota; retired ids never return."""
    added: Counter[str] = Counter()
    for card in cards:
        if card.lesson_id in ledger.retired:
            continue
        if card.lesson_id not in ledger.cards:
            if added[card.kind] >= quotas.get(card.kind, base):
                continue
            added[card.kind] += 1
        ledger.cards[card.lesson_id] = card
    return sum(added.values())


def _refuse_leaks(domain: Domain, harvest: Harvest, cards: Mapping[str, LessonCard]) -> None:
    texts = {f"card:{k}": c.text() for k, c in cards.items()}
    for lesson_id, rows in harvest.situation_rows.items():
        texts |= {f"row:{lesson_id}:{i}": _row_text(r) for i, r in enumerate(rows)}
    texts |= {f"success:{i}": _row_text(r) for i, r in enumerate(harvest.success_rows)}
    hits = domain.leak_hits(texts)
    if hits:
        raise LessonLeakError(f"{len(hits)} texts carry held-out answers: {sorted(hits)}")


def _row_text(row: Row) -> str:
    return "\n".join(turn["content"] for turn in row.messages)


def _utility(ctx: RoundContext, served: str, graded: Sequence[Attempt]) -> list[LessonUtility]:
    """Mark every live card on every graded attempt once, ablate on the baseline half, judge."""
    ledger = ctx.ledger
    live = [c for k, c in ledger.cards.items() if k not in ledger.retired]
    for card in live:
        for attempt in ledger.attempts:
            if not ledger.has_exposure(card.lesson_id, attempt.attempt_id):
                ledger.record_exposure(card.lesson_id, attempt, ctx.domain.mark(card, attempt))
    judged_only = [a for a in graded if in_baseline(a.task_id)]
    pairs = ctx.domain.ablate(served, live, judged_only)
    ledger.pairs.extend(pairs)
    records = [
        LessonRecord(c.lesson_id, c.kind, ledger.rounds_trained.get(c.lesson_id, 0)) for c in live
    ]
    table = judge_lessons(records, ledger.exposures.values(), ledger.pairs)
    ledger.retired |= {row.lesson_id for row in table if row.decision is Decision.DROP}
    tally = Counter(str(row.decision) for row in table)
    ctx.say(
        f"[4/6] utility: {dict(sorted(tally.items()))}, {len(pairs)} new ablation pairs "
        f"({len(ledger.pairs)} pooled)"
    )
    return table


def _train(ctx: RoundContext, index: int, harvest: Harvest, table: Sequence[LessonUtility]) -> dict:
    """Plan the next set from kept lessons and verified successes; the route's learner learns it."""
    domain, ledger = ctx.domain, ctx.ledger
    decisions = {row.lesson_id: row.decision for row in table}
    rows = {
        k: card_rows(ledger.cards[k], domain.memory_system, domain.subject)
        + list(harvest.situation_rows.get(k, ()))
        for k in decisions
    }
    inputs = PlanInputs(index, decisions, rows, harvest.success_rows, domain.max_row_chars)
    plan = plan_training(inputs, ctx.settings.train_mode, _previous(ledger))
    lessons = frozenset(r.lesson_id for r in plan.rows if r.lesson_id in decisions)
    kept = [ledger.cards[k] for k in sorted(lessons)]
    questions = verify_questions(kept, domain.subject)
    job = LearnJob(domain.name, index, plan, domain.memory_system, questions, lessons)
    ctx.say(
        f"[5/6] train ({ctx.learner.route}): {plan.manifest['rows']} rows, {len(lessons)} lessons"
    )
    installed = ctx.learner.learn(job)
    return {
        "model_out": installed.arm,
        "adapter_dir": installed.artifacts.get("adapter_dir", ""),
        "trained_lessons": sorted(installed.lessons),
        "row_keys": sorted(row_key(r) for r in plan.rows),
        "manifest": plan.manifest,
        "kind_scores": kind_scores(table),
    }


def _previous(ledger: Ledger) -> PreviousTraining | None:
    if not ledger.rounds:
        return None
    last = ledger.rounds[-1]
    return PreviousTraining(
        last["adapter_dir"], frozenset(last["trained_lessons"]), frozenset(last["row_keys"])
    )


def _evaluate(ctx: RoundContext, index: int, model: str, trained: frozenset[str]) -> dict:
    """Held-out: the round's arm every round; plain and the start once, at round 0."""
    domain, ledger = ctx.domain, ctx.ledger
    adapter_passed, adapter_graded = _passed_of(domain.evaluate(model, index, trained))
    if ledger.rounds:
        first = ledger.rounds[0]["eval"]
        reference = {k: v for k, v in first.items() if not k.startswith("adapter_")}
    else:
        reference = _references(ctx, index)
    found = {**reference, "adapter_passed": adapter_passed, "adapter_graded": adapter_graded}
    ctx.say(
        f"[6/6] evaluate (held-out): plain {found['plain_passed']}/{found['plain_graded']}, "
        f"start {found['start_passed']}/{found['start_graded']}, "
        f"{model} {adapter_passed}/{adapter_graded}"
    )
    return found


def _references(ctx: RoundContext, index: int) -> dict[str, int]:
    """Plain Glimmer and the start arm on the held-out tasks (one run when they are the same)."""
    plain = _passed_of(ctx.domain.evaluate(ctx.domain.plain_model, index, frozenset()))
    base = ctx.learner.base()
    start = (
        plain
        if base.arm == ctx.domain.plain_model
        else _passed_of(ctx.domain.evaluate(base.arm, index, base.lessons))
    )
    return {
        "plain_passed": plain[0], "plain_graded": plain[1],
        "start_passed": start[0], "start_graded": start[1],
    }  # fmt: skip


def _passed_of(attempts: Sequence[Attempt]) -> tuple[int, int]:
    """(passed, graded); a mostly ungraded held-out run raises instead of scoring an outage."""
    batch = verified(attempts)
    return len(batch.passed), len(batch.graded)


def _counts(graded: Sequence[Attempt]) -> dict[str, int]:
    return {"graded": len(graded), "passed": sum(a.passed for a in graded)}


def _harvest_counts(harvest: Harvest) -> dict[str, int]:
    return {
        "cards_offered": len(harvest.cards),
        "situation_rows": sum(len(rows) for rows in harvest.situation_rows.values()),
        "success_rows": len(harvest.success_rows),
        "unresolved": harvest.unresolved,
    }


def _table_row(row: LessonUtility) -> dict:
    raw = asdict(row)
    raw["estimator"], raw["decision"] = str(row.estimator), str(row.decision)
    return raw
