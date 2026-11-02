import shutil
from pathlib import Path

import pytest

from symbiont import cli
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.painpoint import Signal
from symbiont.readers import READERS
from symbiont.readers.errors import ReadError
from symbiont.readers.findings import count_findings, read

pytestmark = pytest.mark.periphery
FIXTURE = Path(__file__).parent.parent / "fixtures" / "findings" / "valid.jsonl"


def write(tmp_path, *lines):
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_each_finding_becomes_a_private_tagged_record():
    records = list(read(FIXTURE, "p"))
    assert [r.step for r in records] == [1, 2, 3]
    first = records[0]
    assert first.raw.startswith("The retry helper") and first.files == ("src/retry.py",)
    assert {"correction", "finding:mistake", "severity:high", "source:example-reviewer"} <= set(
        first.tags
    )
    assert first.ts == "2026-03-02" and not first.provenance.spark_safe


def test_the_miner_turns_findings_into_pain_points():
    sessions = sessions_of(read(FIXTURE, "p"))
    pains = mine_history(sessions, {})
    assert len(pains) == 3
    assert {p.signature.signal for p in pains} == {Signal.CORRECTION}


def test_reader_is_registered():
    assert READERS["findings"] is read


def test_count_findings_and_folder_reading(tmp_path):
    folder = tmp_path / ".symbiont" / "findings"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "one.jsonl")
    assert count_findings(tmp_path) == 3
    assert len(list(read(folder, "p"))) == 3
    assert count_findings(tmp_path / "empty-repo") == 0


@pytest.mark.parametrize(
    ("line", "line_no", "reason"),
    [
        ("{not json", 2, "not JSON"),
        ('["a"]', 2, "JSON object"),
        ('{"kind": "mistake"}', 2, "'text'"),
        ('{"kind": "oops", "text": "x"}', 2, "'kind'"),
        ('{"kind": "risk", "text": "x", "severity": "huge"}', 2, "'severity'"),
        ('{"kind": "risk", "text": "x", "files": "a.py"}', 2, "'files'"),
        ('{"kind": "risk", "text": "x", "date": "yesterday"}', 2, "'date'"),
        ('{"kind": "risk", "text": "x", "score": 3}', 2, "unknown key 'score'"),
        ("", 2, "not JSON"),
    ],
)
def test_malformed_line_raises_with_file_and_line(tmp_path, line, line_no, reason):
    good = '{"kind": "lesson", "text": "fine"}'
    path = write(tmp_path, good, line)
    with pytest.raises(ReadError) as caught:
        list(read(path, "p"))
    assert caught.value.line_no == line_no and reason in caught.value.reason
    assert str(path) in str(caught.value)


def test_count_findings_raises_instead_of_reporting_zero(tmp_path):
    folder = tmp_path / ".symbiont" / "findings"
    folder.mkdir(parents=True)
    (folder / "x.jsonl").write_text("oops\n", encoding="utf-8")
    with pytest.raises(ReadError):
        count_findings(tmp_path)


def test_mine_imports_the_repo_folder_unless_skipped(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / ".symbiont" / "findings").mkdir(parents=True)
    shutil.copy(FIXTURE, repo / ".symbiont" / "findings" / "a.jsonl")
    base = ["--repo", str(repo), "--data-dir", str(tmp_path / "d")]
    assert cli.main(["mine", "--project", "p", *base]) == 0
    assert "3 lessons from 1 logs" in capsys.readouterr().out
    assert cli.main(["mine", "--project", "q", "--no-findings", *base]) == 0
    assert "0 lessons from 0 logs" in capsys.readouterr().out
    assert (
        cli.main(["mine", "--project", "r", "--no-findings", "--findings", str(FIXTURE), *base])
        == 0
    )
    assert "3 lessons" in capsys.readouterr().out
