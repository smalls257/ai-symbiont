"""What the loop trains, per route, and the start it learns from.

Route B trains Glimmer itself (an adapter installed as `Muse-Glimmer-30B-<domain>[-habits]-r<N>`);
Route A trains the warner and the Llama 1B memory model, and its arm is the unchanged user model
plus notes. `Start` is plain or a shared cross-repo habits base, so the loop can measure rounds
and lessons needed to beat each start on unseen work (`ledger.rounds_to_improve`).
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from trainer import HostTrainer, TrainJob
from training_plan import TrainingPlan

MODEL_PREFIX = "Muse-Glimmer-30B"


class Route(StrEnum):
    """Which thing the loop trains."""

    GLIMMER_ADAPTER = "route-b-glimmer-adapter"
    WARNER_AND_MEMORY = "route-a-warner-and-memory"


class Start(StrEnum):
    """Where round 0 starts from."""

    PLAIN = "plain"
    SHARED_HABITS = "shared-habits"


class RouteNotWiredError(RuntimeError):
    """A real learner was asked to train before its inputs exist; names what is missing."""


@dataclass(frozen=True)
class Installed:
    """The arm attempts are made with, and what it is made of (host paths, model names)."""

    arm: str
    artifacts: dict[str, str] = field(default_factory=dict)
    lessons: frozenset[str] = frozenset()  # lesson ids the arm learned (the base's for a start)


@dataclass(frozen=True)
class LearnJob:
    """One round's learning: the plan, the round, the verify inputs."""

    domain: str
    round_index: int
    plan: TrainingPlan
    system: str
    questions: Sequence[dict[str, str]]
    lesson_ids: frozenset[str]


@dataclass(frozen=True)
class BaseArm:
    """A starting point as configured: its arm name, artifacts and the lessons it already holds."""

    arm: str
    artifacts: dict[str, str] = field(default_factory=dict)
    lessons: frozenset[str] = frozenset()


class Learner(Protocol):
    """A route plugin: the starting arm, and one round's learning."""

    route: Route
    start: Start

    def base(self) -> Installed:
        """The arm round 0 attempts with (plain, or the shared habits base)."""
        ...

    def learn(self, job: LearnJob) -> Installed:
        """Train, install and verify; raises on any failed step."""
        ...


def arm_name(route: Route, start: Start, domain: str, round_number: int) -> str:
    """The round's arm name; the start is in it so two curves never share a model name."""
    habits = "-habits" if start is Start.SHARED_HABITS else ""
    if route is Route.GLIMMER_ADAPTER:
        return f"{MODEL_PREFIX}-{domain}{habits}-r{round_number}"
    return f"user-model+symbiont-{domain}{habits}-r{round_number}"


@dataclass
class GlimmerAdapterLearner:
    """Route B for real: HostTrainer on the training host; the shared base is an adapter dir."""

    trainer: HostTrainer
    start: Start
    starting: BaseArm
    route: Route = Route.GLIMMER_ADAPTER

    def base(self) -> Installed:
        """Plain Glimmer, or the configured habits adapter."""
        return Installed(self.starting.arm, self.starting.artifacts, self.starting.lessons)

    def learn(self, job: LearnJob) -> Installed:
        """One adapter; a from-scratch plan under the habits start begins at the habits adapter."""
        adapter_set = f"{job.domain}{'-habits' if self.start is Start.SHARED_HABITS else ''}"
        adapter_set += f"-r{job.round_index + 1}"
        model = arm_name(self.route, self.start, job.domain, job.round_index + 1)
        train = TrainJob(
            _from_base(job.plan, self.starting), model, adapter_set, job.system, job.questions,
            job.lesson_ids,
        )  # fmt: skip
        adapter_dir = self.trainer.train_and_install(train)
        return Installed(model, {"adapter_dir": adapter_dir}, job.lesson_ids)


def _from_base(plan: TrainingPlan, starting: BaseArm) -> TrainingPlan:
    """A plan with no previous adapter starts from the base adapter, when the base has one."""
    base_dir = starting.artifacts.get("adapter_dir")
    if plan.start_from or not base_dir:
        return plan
    return TrainingPlan(plan.rows, base_dir, {**plan.manifest, "starts_from_base": True})


@dataclass
class WarnerAndMemoryLearner:
    """Route A for real: not wired yet, and says so instead of training something else."""

    start: Start
    starting: BaseArm
    route: Route = Route.WARNER_AND_MEMORY

    def base(self) -> Installed:
        """The user model with the starting warner and memory model."""
        return Installed(self.starting.arm, self.starting.artifacts, self.starting.lessons)

    def learn(self, job: LearnJob) -> Installed:
        """Raises RouteNotWiredError naming the two inputs Route A's trainers still lack."""
        raise RouteNotWiredError(
            "Route A round learning needs (1) scripts/routea/train_memory.py to take loop cards "
            "(it reads Store lessons today) and (2) a per-step export of the round's verified "
            "attempts for fit_warner.py (it reads the public OpenHands pool); "
            f"round {job.round_index} of {job.domain} not trained"
        )


@dataclass
class FakeLearner:
    """Dry run for either route: registers which lessons each arm holds in the fake domain."""

    route: Route
    start: Start
    learned: MutableMapping[str, frozenset[str]]
    base_lessons: frozenset[str] = frozenset()
    plain_arm: str = "fake-plain"
    say: Callable[[str], None] = print

    def base(self) -> Installed:
        """Plain, or a base arm that already holds the shared habit lessons."""
        if self.start is Start.PLAIN:
            return Installed(self.plain_arm)
        arm = arm_name(self.route, self.start, "base", 0)
        self.learned[arm] = self.base_lessons
        return Installed(arm, {"base": "fake shared habits"}, self.base_lessons)

    def learn(self, job: LearnJob) -> Installed:
        """No GPU: the arm holds the job's lesson ids, plus the base's under the habits start."""
        if not job.plan.rows:
            raise ValueError(f"{job.domain} round {job.round_index}: refusing an empty set")
        arm = arm_name(self.route, self.start, job.domain, job.round_index + 1)
        held = job.lesson_ids | (self.base_lessons if self.start is Start.SHARED_HABITS else set())
        self.learned[arm] = frozenset(held)
        what = "adapter" if self.route is Route.GLIMMER_ADAPTER else "warner + memory model"
        self.say(f"  fake {what}: {len(job.plan.rows)} rows; installed {arm}; plain stays plain")
        return Installed(arm, {"fake": what}, frozenset(held))
