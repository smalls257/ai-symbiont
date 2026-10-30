"""Pure parts of the dataset export script; the network part is run by hand."""

import importlib.util
from pathlib import Path

import pytest

from symbiont.readers.errors import ReadError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "datasets" / "export_nebius_sqlglot.py"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openhands" / "two_sessions.jsonl"


@pytest.fixture(scope="module")
def export():
    spec = importlib.util.spec_from_file_location("export_nebius_sqlglot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_token_from_env_wins_over_file(export, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("hf_file\n")
    assert export.find_token({"HF_TOKEN": "hf_env"}, token_file) == "hf_env"
    assert export.find_token({}, token_file) == "hf_file"
    assert export.find_token({}, tmp_path / "missing") is None


def test_rate_limit_is_recognised(export):
    assert export.is_rate_limited(Exception("HTTP Error: HTTP GET error on '...' (HTTP 429)"))
    assert export.is_rate_limited(Exception("Too Many Requests"))
    assert not export.is_rate_limited(Exception("HTTP 404 Not Found"))


def test_check_export_counts_rows_and_sessions(export):
    counts = export.check_export(FIXTURE)
    assert counts.rows >= 1 and counts.records > counts.rows


def test_check_export_refuses_an_empty_file(export, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(SystemExit, match="no rows"):
        export.check_export(empty)


def test_check_export_names_an_unreadable_line(export, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(FIXTURE.read_text().splitlines()[0] + "\n{\n")
    with pytest.raises(ReadError) as caught:
        export.check_export(bad)
    assert caught.value.line_no == 2
