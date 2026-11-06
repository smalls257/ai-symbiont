"""Builders shared by the nightly tests: judge-shaped lessons, chat rows and fake tools."""

import itertools
import json
import struct
from pathlib import Path

from store_builders import save_lessons
from symbiont.core.judge_format import JUDGE_SYSTEM
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.service.nightly_rows import ChatRow
from symbiont.service.nightly_run import NightTools

PROJECT = "demo"


def failed_command_lesson(index, fix=None, error=None, files=("app/mod.py",)):
    """A failed-command lesson with a quote `$ cmd` + error line and one fix command."""
    signature = Signature(Signal.FAILED_COMMAND, (f"tool{index}", f"module{index}", "Oops"))
    pain = PainPoint(signature, f"s{index}", 1, ((f"s{index}", 1),))
    quote = f"$ pytest tests/test_{index}.py\n{error or f'Oops{index}: broken'}"
    steps = (f"ran `{fix or f'pytest tests/test_{index}.py -q'}`",)
    return Lesson(pain, quote, steps, None, True, pain.record_refs, files=files)


def chat(system, user, answer) -> ChatRow:
    """One mlx-lm chat row."""
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ]
    }


def general_rows(count=40):
    """Judge rows from another repository, half yes and half no."""
    rows = []
    for index in range(count):
        lesson = f"In other/repo, `a{index}` failed; run `b{index}`."
        user = f"Situation:\nfoo{index} failed\n\nLesson:\n{lesson}\n\nDoes this lesson apply?"
        rows.append(chat(JUDGE_SYSTEM, user, "yes" if index % 2 else "no"))
    return rows


def habit_rows(count=5):
    """Habit rows."""
    return [chat("habit", f"Recall habit {index}", f"Check {index}") for index in range(count)]


class FakeNight:
    """The night's tools with no machine: records commands, writes what a trainer would."""

    def __init__(self, backend, exit_code=0, trainer_writes=True):
        self.commands, self.said, self.environments = [], [], []
        self.backend_name = backend
        self.exit_code, self.trainer_writes = exit_code, trainer_writes
        self.ticks = itertools.count()
        self.judge_calls = []

    def tools(self):
        return NightTools(
            run=self.run,
            clock=lambda: float(next(self.ticks)),
            timestamp=lambda: "2026-11-03T03:00:00+00:00",
            say=self.said.append,
            backend=lambda: self.backend_name,
            torch_script=lambda: Path("/scripts/train_lora_torch.py"),
            check_python=lambda python, backend: None,
            tell_judge=self.tell_judge,
        )

    def run(self, python, args, log, extra):
        command = [python, *args]
        self.commands.append(command)
        self.environments.append(dict(extra))
        log.write_text("trainer output")
        if self.exit_code == 0 and self.trainer_writes:
            folder = Path(
                command[
                    command.index("--adapter-path" if "--adapter-path" in command else "--adapter")
                    + 1
                ]
            )
            (folder / "adapters.safetensors").write_bytes(mlx_adapter_bytes())
            (folder / "adapter_model.safetensors").write_bytes(b"peft")
            (folder / "adapter_config.json").write_text("{}")
        return self.exit_code

    def tell_judge(self, url, adapter, base):
        self.judge_calls.append((url, adapter, base))
        return f"judge told {url}"


def mlx_adapter_bytes():
    raw = bytes(16)
    head = json.dumps(
        {"m.lora_a": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]}}
    ).encode()
    return struct.pack("<Q", len(head)) + head + raw


def write_kit(root):
    """A judge kit folder with a base marker and both row files."""
    (root / "base").mkdir(parents=True)
    (root / "base" / "config.json").write_text("{}")
    for name, rows in (("general-rows.jsonl", general_rows(60)), ("habits.jsonl", habit_rows(8))):
        (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))


def night_plan(tmp_path, lessons=6, url="http://127.0.0.1:8861"):
    """A plan over a real store with `lessons` lessons and a complete kit."""
    from symbiont.service.nightly_run import NightPlan
    from symbiont.store.local import Source, Store

    data = tmp_path / "data"
    data.mkdir()
    save_lessons(
        Store.open(data / "store.db"),
        PROJECT,
        [Source(PROJECT, "claude_code", "x")],
        [failed_command_lesson(i) for i in range(lessons)],
        held_out_tasks=frozenset(),
    )
    write_kit(tmp_path / "kit")
    return NightPlan(PROJECT, data, data / "nightly", tmp_path / "kit", url, "py")
