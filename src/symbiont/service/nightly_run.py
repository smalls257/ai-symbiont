"""One night: lessons to rows, rows to an adapter, adapter to a record and a judge.

Every stage finishes or raises `NightFailedError` naming the stage and its log. The record is
written only after the trainer exited 0, so a failed night leaves the older record, which then
reads as stale. Stage seconds print as each ends. The world is injected through `NightTools`.
"""

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from symbiont.miner.lessons import Lesson
from symbiont.miner.twins import merge_twins
from symbiont.service.judge_start import JudgeStart, judge_device, port_of
from symbiont.service.nightly import (
    NightlyRecord,
    lessons_digest,
    write_record,
)
from symbiont.service.nightly_backend import (
    Backend,
    TrainJob,
    iterations,
    mlx_command,
    mlx_lora_config,
    peft_config,
    torch_command,
    torch_environment,
)
from symbiont.service.nightly_kit import JudgeKit, open_kit, read_rows
from symbiont.service.nightly_peft import mlx_to_peft
from symbiont.service.nightly_rows import night_rows, trainable_lessons
from symbiont.store.local import Store

EXIT_FAILED = 1
EXIT_NO_LESSONS = 2
ADAPTER_FILE = "adapter_model.safetensors"
MLX_ADAPTER_FILE = "adapters.safetensors"
ADAPTER_CONFIG = "adapter_config.json"
VALID_ROWS = (
    8  # plug_r4_cont.write_repo: the validation file is the first rows, never read for loss
)

# (interpreter, arguments after `python`, log file, extra environment) -> exit code
Runner = Callable[[str, Sequence[str], Path, Mapping[str, str]], int]
Say = Callable[[str], None]


class NightFailedError(RuntimeError):
    """A stage of the night failed; nothing was recorded and the older record still stands."""


class NoLessonsError(NightFailedError):
    """The repository has no lessons, so there is nothing to train on."""


@dataclass(frozen=True)
class NightPlan:
    """What one night is asked to do and where its files go."""

    project: str
    data_dir: Path
    nightly_dir: Path
    kit_dir: Path
    judge_url: str
    trainer_python: str
    # The Python the judge server runs on; the record keeps it so the server can be started again.
    judge_python: str = "python3"


@dataclass(frozen=True)
class NightTools:
    """The world the night touches; real ones in `nightly_tools.py`, fakes in tests."""

    run: Runner
    clock: Callable[[], float]
    timestamp: Callable[[], str]
    say: Say
    backend: Callable[[], Backend]
    torch_script: Callable[[], Path]
    check_python: Callable[[str, Backend], None]
    tell_judge: Callable[[str, Path, Path], str]


class Timeline:
    """Stage wall times, printed as each stage ends."""

    def __init__(self, tools: NightTools) -> None:
        """Start the whole-night clock."""
        self._tools = tools
        self._started = tools.clock()
        self.stages: list[tuple[str, float]] = []

    def stage[T](self, name: str, work: Callable[[], T]) -> T:
        """Run `work`, record and print its seconds (also when it raises)."""
        began = self._tools.clock()
        try:
            return work()
        finally:
            seconds = self._tools.clock() - began
            self.stages.append((name, seconds))
            self._tools.say(f"  {name}: {seconds:.1f}s")

    def total(self) -> float:
        """Seconds since the night began."""
        return self._tools.clock() - self._started


def run_night(plan: NightPlan, tools: NightTools) -> int:
    """Train the project's nightly judge. Returns 0, EXIT_NO_LESSONS or EXIT_FAILED."""
    timeline = Timeline(tools)
    try:
        count = _train_and_record(plan, tools, timeline)
    except NoLessonsError as nothing:
        tools.say(f"symbiont nightly: {nothing}")
        return EXIT_NO_LESSONS
    except (NightFailedError, OSError, ValueError) as failed:
        tools.say(f"symbiont nightly: FAILED: {failed}")
        return EXIT_FAILED
    tools.say(f"trained on {count} lessons in {timeline.total():.1f}s ({_breakdown(timeline)})")
    return 0


def _breakdown(timeline: Timeline) -> str:
    """The stages and seconds on one line."""
    return ", ".join(f"{name} {seconds:.1f}s" for name, seconds in timeline.stages)


def _train_and_record(plan: NightPlan, tools: NightTools, timeline: Timeline) -> int:
    """The stages in order; returns how many lessons the adapter was trained on."""
    kit = open_kit(plan.kit_dir)  # first: a missing kit must not cost a read of the lessons
    work = plan.nightly_dir / plan.project / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    lessons = timeline.stage("read lessons", lambda: _stored_lessons(plan))
    backend = tools.backend()
    tools.check_python(plan.trainer_python, backend)
    tools.say(f"{len(lessons)} lessons; training on {backend.value}")
    rows = timeline.stage("build rows", lambda: _write_rows(plan, kit, lessons, work))
    job = _job(kit, work, rows)
    timeline.stage("train", lambda: _train(plan, tools, backend, job, work))
    adapter = timeline.stage("install adapter", lambda: _installed(plan, backend, job, kit))
    start = JudgeStart(
        plan.judge_python,
        str(kit.base),
        str(adapter),
        judge_device(backend),
        port_of(plan.judge_url),
    )
    record = NightlyRecord(
        lessons_digest(lessons),
        plan.judge_url,
        len(lessons),
        tools.timestamp(),
        backend.value,
        start.as_json(),
    )
    timeline.stage("write record", lambda: write_record(plan.nightly_dir, plan.project, record))
    tools.say(tools.tell_judge(plan.judge_url, adapter, kit.base))
    tools.say("service: the running symbiont service reads the new record on its next recall")
    return len(lessons)


def _stored_lessons(plan: NightPlan) -> list[Lesson]:
    """The project's lessons with twins merged; NoLessonsError when there are none."""
    path = plan.data_dir / "store.db"
    if not path.is_file():
        raise NoLessonsError(f"no symbiont data at {path}; mine this repository's history first")
    lessons = merge_twins(Store.open(path).lessons(plan.project))
    if not lessons:
        raise NoLessonsError(
            f"{plan.project} has no stored lessons to train on; run `symbiont repo mine` first"
        )
    return list(lessons)


def lesson_count(plan: NightPlan) -> int:
    """How many lessons a night would train on; NoLessonsError when there are none."""
    return len(_stored_lessons(plan))


def _write_rows(plan: NightPlan, kit: JudgeKit, lessons: list[Lesson], work: Path) -> int:
    """Write train.jsonl and valid.jsonl under work/data; returns the row count."""
    items = trainable_lessons(lessons, plan.project)
    rows = night_rows(items, read_rows(kit.general_rows), read_rows(kit.habits))
    data = work / "data"
    data.mkdir()
    lines = [json.dumps(row) + "\n" for row in rows]
    (data / "train.jsonl").write_text("".join(lines), encoding="utf-8")
    (data / "valid.jsonl").write_text("".join(lines[:VALID_ROWS]), encoding="utf-8")
    return len(rows)


def _job(kit: JudgeKit, work: Path, rows: int) -> TrainJob:
    """The training run for `rows` rows, fresh from the fixed base (never stacked)."""
    return TrainJob(
        kit.base, work / "data", iterations(rows), work / "adapter-new", work / "lora.yaml"
    )


def _train(plan: NightPlan, tools: NightTools, backend: Backend, job: TrainJob, work: Path) -> None:
    """Run the trainer; any exit but 0 raises with the log's path."""
    job.adapter.mkdir()
    if backend is Backend.MLX:
        job.config.write_text(mlx_lora_config(job.iters), encoding="utf-8")
        args, extra = mlx_command(job), {}
    else:
        args, extra = torch_command(tools.torch_script(), job), torch_environment()
    log = work / "train.log"
    code = tools.run(plan.trainer_python, args, log, extra)
    if code != 0:
        raise NightFailedError(f"the trainer exited {code}; its log is {log}")


def _installed(plan: NightPlan, backend: Backend, job: TrainJob, kit: JudgeKit) -> Path:
    """Put the new adapter, in PEFT layout and nothing else, at `<project>/adapter`.

    The old adapter is replaced only now, after training exited 0, so a failed night keeps it.
    Returns that folder.
    """
    ready = job.adapter.with_name("adapter-peft")
    ready.mkdir()
    if backend is Backend.MLX:
        converted = mlx_to_peft((job.adapter / MLX_ADAPTER_FILE).read_bytes())
        (ready / ADAPTER_FILE).write_bytes(converted)
        (ready / ADAPTER_CONFIG).write_text(
            json.dumps(peft_config(kit.base), indent=1), encoding="utf-8"
        )
    else:
        for name in (ADAPTER_FILE, ADAPTER_CONFIG):
            _copied(job.adapter / name, ready / name)
    final = plan.nightly_dir / plan.project / "adapter"
    shutil.rmtree(final, ignore_errors=True)
    os.replace(ready, final)
    return final


def _copied(source: Path, target: Path) -> None:
    """Copy one file the trainer must have written; NightFailedError when it did not."""
    if not source.is_file():
        raise NightFailedError(f"the trainer wrote no {source.name} in {source.parent}")
    shutil.copyfile(source, target)
