"""Glimmer and GPU hours per loop round, per domain, from measured rates [hypothesis on totals].

Every rate names the run it was measured in, so a wrong estimate traces to the number that
moved. Totals multiply measured rates by planned counts. Pure: no clock, no host.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Coding (sqlglot, CAL2, 4 Glimmer slots, step cap 50, wall cap 45 min):
# general-lessons pilot plan: 36 runs in 2 to 2.5 h wall at 4 workers -> 3.75 min wall per run
# (progress 2026-10-28 15:04: 21.4 s/step at 4 slots). [measured rate, planned count]
CODING_WALL_H_PER_RUN = 2.25 / 36
# Route B sqlglot adapter: 736 steps in 76.6 min -> 6.2 s per step (progress 2026-10-28 16:31).
CODING_S_PER_STEP = 76.6 * 60 / 736
# Freedoom (act1-learning-report section 3): 32 s per decision serial, 2 slots, about 1.3x slower
# per slot when both are busy; Freedoom rows are longer: 9 to 11 s per step (upper end used).
FREEDOOM_S_PER_DECISION = 32
FREEDOOM_SLOT_SLOWDOWN = 1.3
FREEDOOM_SLOTS = 2
FREEDOOM_S_PER_STEP = 11
# Route B recipe: 8 epochs, batch 4 -> 2 steps per row; load + GGUF convert about 6 min
# (routeb-prep); install restarts the router and waits for health, verify asks 3 x 2 x 2 questions.
STEPS_PER_ROW = 8 / 4
LOAD_CONVERT_H = 6 / 60
INSTALL_VERIFY_H = 10 / 60


@dataclass(frozen=True)
class DomainRound:
    """Planned counts for one round of one domain."""

    domain: str
    attempts: str  # what the attempt step runs
    attempt_units: int  # coding: runs; Freedoom: decisions
    eval_units: int  # held-out, the round's adapter
    plain_eval_units: int  # held-out, plain Glimmer: round 0 only
    ablation_units: int  # with-card runs (the round's own attempt is the without side)
    rows: int  # planned training rows (kept cards x about 3, plus success rows)


DOMAINS = {
    "coding-sqlglot": DomainRound(
        "coding-sqlglot",
        "CAL2 --fixed-runs 1 --model <round model> on 24 training tasks (cap 50, 4 workers)",
        attempt_units=24,
        eval_units=18,
        plain_eval_units=18,
        ablation_units=6,
        rows=150,
    ),
    "freedoom": DomainRound(
        "freedoom",
        "collect_episodes.py glimmer_plain --glimmer-model <round model>, 5 training levels x "
        "2 seeds, 16-decision cap",
        attempt_units=10 * 16,
        eval_units=4 * 16,  # MAP04 and MAP08 x seeds 3-4
        plain_eval_units=4 * 16,
        ablation_units=0,  # the collector has no lesson-in-prompt path yet
        rows=120,
    ),
}


def glimmer_hours(plan: DomainRound, units: int) -> float:
    """Wall hours on Glimmer for `units` runs or decisions of this domain."""
    if plan.domain == "freedoom":
        serial = units * FREEDOOM_S_PER_DECISION / 3600
        return serial * FREEDOOM_SLOT_SLOWDOWN / FREEDOOM_SLOTS
    return units * CODING_WALL_H_PER_RUN


def gpu_hours(plan: DomainRound) -> float:
    """Training-host hours with Glimmer paused: train, convert, install and verify."""
    seconds = FREEDOOM_S_PER_STEP if plan.domain == "freedoom" else CODING_S_PER_STEP
    return plan.rows * STEPS_PER_ROW * seconds / 3600 + LOAD_CONVERT_H + INSTALL_VERIFY_H


def round_plan(domain: str) -> dict:
    """The round's steps and hours, for `run_loop.py plan`; nothing runs."""
    plan = DOMAINS[domain]
    later = plan.attempt_units + plan.eval_units + plan.ablation_units
    first = later + plan.plain_eval_units
    return {
        "label": "estimate [hypothesis]: measured rates x planned counts",
        **asdict(plan),
        "steps": [
            f"1 attempt: {plan.attempts}",
            "2 verify: graded outcomes only; ungraded counted, >25% ungraded stops the round",
            "3 harvest: three-part cards from all graded training attempts; open cards when no "
            "verified success got past the mistake; held-out leak scan on every text",
            "4 lesson utility: marks per card per attempt, ablation sample, keep/probation/"
            "down-weight/drop, kind quotas for the next harvest",
            "5 train: ops/routeb_nightly_host.sh train/install/verify via ops/gpu_run.sh "
            "(Glimmer paused for training only), Muse-Glimmer-30B-<domain>-r<N>",
            "6 evaluate: held-out, the round's model; plain once at round 0",
        ],
        "glimmer_hours_round_0": round(glimmer_hours(plan, first), 2),
        "glimmer_hours_later_rounds": round(glimmer_hours(plan, later), 2),
        "gpu_hours_per_round": round(gpu_hours(plan), 2),
        "route_a_note": "Route A trains no Glimmer: the same attempt and evaluation hours on the "
        "user's model, plus a Llama 1B memory LoRA and a warner refit off the Strix (not wired)",
    }
