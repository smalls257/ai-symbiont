"""`symbiont mine`: re-reads the registered logs and prints resolution coverage, counts only."""

from dataclasses import replace

import pytest

from record_builders import run, session
from symbiont import cli
from symbiont.records.schema import dump_jsonl, load_jsonl

pytestmark = pytest.mark.periphery

TEST = "pytest tests/test_parser.py"


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "READERS", {"records-jsonl": read_records_jsonl})
    fixed = session(run(TEST, 1, "ImportError"), run("pip install pyyaml"), run(TEST, 0, "ok"))
    never = [replace(r, session_id="s2") for r in session(run(TEST, 1, "ImportError"))]
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl(fixed + never, fh)
    return path


def test_mine_prints_lesson_count_and_per_signal_coverage(tmp_path, logs, capsys):
    argv = ["mine", "--project", "p", "--data-dir", str(tmp_path / "d")]
    assert cli.main([*argv, "--source", f"records-jsonl={logs}"]) == 0
    out = capsys.readouterr().out
    assert "2 lessons from 1 logs" in out
    assert "failed_command: 1 of 2 resolved" in out and "loop: 0 of 0 resolved" in out
    assert "ImportError" not in out and "pyyaml" not in out
    assert cli.main(argv) == 0, "a second run re-reads the registered log"
    assert "2 lessons from 1 logs" in capsys.readouterr().out


def test_mine_reports_a_held_out_task_and_fails(tmp_path, logs, capsys):
    held = [replace(r, task_id="o__r-1") for r in read_records_jsonl(logs, "p")]
    with logs.open("w") as fh:
        dump_jsonl(held, fh)
    argv = ["mine", "--project", "p", "--data-dir", str(tmp_path / "d"), "--held-out", "o/r#1"]
    assert cli.main([*argv, "--source", f"records-jsonl={logs}"]) == 1
    assert "held out" in capsys.readouterr().err
