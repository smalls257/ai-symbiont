"""QG-TST-05: the score arithmetic and the bar. mutmut itself is minutes long and runs from
scripts/gates/mutation.sh at release, so these tests feed the scorer stats files directly."""

import json
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[2] / "scripts" / "gates"
sys.path.insert(0, str(GATES))

import mutation_score  # noqa: E402


def _stats(tmp_path: Path, killed: int, survived: int, timeout: int = 0) -> Path:
    total = killed + survived + timeout
    path = tmp_path / "stats.json"
    path.write_text(
        json.dumps(
            {
                "killed": killed,
                "survived": survived,
                "timeout": timeout,
                "no_tests": 0,
                "total": total,
            }
        )
    )
    return path


def test_a_suite_that_kills_four_in_five_mutants_meets_the_bar(tmp_path, capsys):
    assert mutation_score.main(["x", str(_stats(tmp_path, killed=80, survived=20))]) == 0
    assert "80.0% killed" in capsys.readouterr().out


def test_a_suite_that_kills_less_fails_and_a_timeout_counts_as_killed(tmp_path):
    assert mutation_score.main(["x", str(_stats(tmp_path, killed=79, survived=21))]) == 1
    assert mutation_score.main(["x", str(_stats(tmp_path, killed=79, survived=20, timeout=1))]) == 0


def test_no_mutants_or_no_stats_cannot_judge(tmp_path):
    assert mutation_score.main(["x", str(_stats(tmp_path, 0, 0))]) == 2
    assert mutation_score.main(["x", str(tmp_path / "absent.json")]) == 2


def test_survivors_are_listed_by_mutant_name(tmp_path, capsys):
    results = tmp_path / "results.txt"
    results.write_text("    a.b.x_f__mutmut_1: survived\n    a.b.x_g__mutmut_2: killed\n")
    mutation_score.main(["x", str(_stats(tmp_path, 90, 10)), str(results)])
    out = capsys.readouterr().out
    assert "survived a.b.x_f__mutmut_1" in out and "x_g" not in out


@pytest.mark.parametrize("stats", [{"killed": 1}, {}])
def test_a_stats_file_without_the_expected_keys_cannot_judge(tmp_path, stats):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats))
    assert mutation_score.main(["x", str(path)]) == 2
