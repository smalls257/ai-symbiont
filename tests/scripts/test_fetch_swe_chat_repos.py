"""Offline tests of the repo-scoped transcript fetch: labels, license and dest refusals."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

DATASETS = Path(__file__).resolve().parents[2] / "scripts" / "datasets"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DATASETS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def base():
    sys.path.insert(0, str(DATASETS))
    load("fetch_swe_chat")
    return load("fetch_swe_chat_repos")


def test_labels_placed_by_uuid_other_lines_untouched(base, tmp_path):
    keep_a = b'{"type": "assistant",  "uuid":"u1","x":1}'
    keep_b = b"[1,  2]"
    user = b'{"type":"user","uuid":"u2","message":"hi"}'
    other = b'{"type":"user","uuid":"u9"}'
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"\n".join([keep_a, user, keep_b, other]) + b"\n")
    placed = base.place_labels(path, {"u1": "correction", "u2": "rejection"})
    lines = path.read_bytes().split(b"\n")
    assert placed == 1
    assert lines[0] == keep_a and lines[2] == keep_b and lines[3] == other
    assert json.loads(lines[1])["prompt_pushback"] == "rejection"


def write_tables(tmp_path, license_type="MIT"):
    import duckdb

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE s(session_id VARCHAR, repo_id VARCHAR, agent VARCHAR, "
        "transcript_path VARCHAR)"
    )
    con.executemany(
        "INSERT INTO s VALUES (?,?,?,?)",
        [
            ("s1", "o/r", "Claude Code", "transcripts/s1.jsonl"),
            ("s2", "o/r", "codex", "transcripts/s2.jsonl"),
        ],
    )
    con.execute(f"COPY s TO '{tmp_path / 'sessions.parquet'}' (FORMAT PARQUET)")
    con.execute("CREATE TABLE r(repo_id VARCHAR, name VARCHAR, license_type VARCHAR)")
    con.execute("INSERT INTO r VALUES ('o/r', 'r', ?)", [license_type])
    con.execute(f"COPY r TO '{tmp_path / 'repositories.parquet'}' (FORMAT PARQUET)")


def test_non_permissive_repo_refused(base, tmp_path):
    write_tables(tmp_path, "AGPL-3.0")
    with pytest.raises(SystemExit, match="not permissively licensed"):
        base.claude_sessions(tmp_path, ["r"])


def test_unknown_repo_refused(base, tmp_path):
    write_tables(tmp_path)
    with pytest.raises(SystemExit, match="unknown repo"):
        base.claude_sessions(tmp_path, ["nope"])


def test_only_claude_sessions_selected(base, tmp_path):
    write_tables(tmp_path)
    assert base.claude_sessions(tmp_path, ["r"]) == [("r", "o/r", "s1", "transcripts/s1.jsonl")]


def test_dest_inside_git_repo_refused(base, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(SystemExit, match="refusing --dest"):
        base.main(["--dest", str(tmp_path / "out"), "--repos", "r"])


def test_end_to_end_with_seams(base, tmp_path, monkeypatch, capsys):
    write_tables(tmp_path)
    (tmp_path / "REVISION").write_text("rev1\n")
    stage = tmp_path / ".transcripts-stage"

    def fake_download(paths, local_dir, rev):
        assert rev == "rev1"
        for rel in paths:
            target = Path(local_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'{"type":"user","uuid":"a"}\n')

    monkeypatch.setattr(base, "download_transcripts", fake_download)
    monkeypatch.setattr(base, "fetch_labels", lambda rev, repo_ids: [("s1", "a", "correction")])
    monkeypatch.setattr(base, "check_dest", lambda d: d)
    base.main(["--dest", str(tmp_path), "--repos", "r"])
    out = tmp_path / "repos" / "r" / "s1.jsonl"
    assert json.loads(out.read_text())["prompt_pushback"] == "correction"
    assert not stage.exists()
    assert "sessions 1, labels wanted 1, labels placed 1" in capsys.readouterr().out


def test_missing_revision_exits_without_pinning(base, tmp_path):
    with pytest.raises(SystemExit, match="fetch_swe_chat.py small first"):
        base.main(["--dest", str(tmp_path), "--repos", "r"])
    assert not (tmp_path / "REVISION").exists()


def test_repo_without_claude_sessions_refused(base, tmp_path):
    write_tables(tmp_path)
    import duckdb

    duckdb.execute(
        f"COPY (SELECT * FROM '{tmp_path / 'sessions.parquet'}' WHERE agent='codex') "
        f"TO '{tmp_path / 'sessions.parquet'}.new' (FORMAT PARQUET)"
    )
    (tmp_path / "sessions.parquet.new").replace(tmp_path / "sessions.parquet")
    with pytest.raises(SystemExit, match="no Claude Code sessions"):
        base.claude_sessions(tmp_path, ["r"])


def test_failed_label_query_leaves_repos_empty(base, tmp_path, monkeypatch):
    write_tables(tmp_path)
    (tmp_path / "REVISION").write_text("rev1\n")

    def fake_download(paths, local_dir, rev):
        target = Path(local_dir) / paths[0]
        target.parent.mkdir(parents=True)
        target.write_bytes(b'{"type":"user","uuid":"a"}\n')

    def broken(rev, repo_ids):
        raise RuntimeError("query failed")

    monkeypatch.setattr(base, "download_transcripts", fake_download)
    monkeypatch.setattr(base, "fetch_labels", broken)
    monkeypatch.setattr(base, "check_dest", lambda d: d)
    with pytest.raises(RuntimeError):
        base.main(["--dest", str(tmp_path), "--repos", "r"])
    assert not (tmp_path / "repos").exists()


def test_malformed_line_names_path_and_line_not_text(base, tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b'{"type":"user","uuid":"u"}\n{secret text\n')
    with pytest.raises(SystemExit) as exc:
        base.place_labels(path, {"u": "correction"})
    assert "line 2" in str(exc.value) and str(path) in str(exc.value)
    assert "secret" not in str(exc.value)


def test_non_string_uuid_ignored(base, tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b'{"type":"user","uuid":["x"]}\n')
    assert base.place_labels(path, {"x": "correction"}) == 0


def test_label_query_selects_only_the_three_columns(base, monkeypatch):
    seen = []

    class Con:
        def execute(self, sql, params):
            seen.append(sql)
            return self

        def fetchall(self):
            return []

    monkeypatch.setattr(base, "remote_con", lambda rev: Con())
    base.fetch_labels("rev1", ["o/r"])
    select = seen[0].split(" FROM ")[0]
    assert select == "SELECT session_id, source_entry_uuid, prompt_pushback"
