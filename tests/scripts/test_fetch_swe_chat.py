"""Safety rails of the SWE-chat fetch script; the network part is run by hand."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "datasets" / "fetch_swe_chat.py"


@pytest.fixture(scope="module")
def fetch():
    spec = importlib.util.spec_from_file_location("fetch_swe_chat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LimitedError(Exception):
    def __init__(self):
        super().__init__("HTTP 429 Too Many Requests")


def test_backoff_retries_then_succeeds(fetch):
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise LimitedError()
        return "ok"

    assert fetch.with_backoff("x", flaky, sleep=waits.append) == "ok"
    assert len(waits) == 2 and waits[1] > waits[0]


def test_backoff_fails_loudly_when_exhausted(fetch):
    waits = []
    with pytest.raises(fetch.RateLimitExhaustedError, match="after 3 attempts"):
        fetch.with_backoff("x", lambda: (_ for _ in ()).throw(LimitedError()), waits.append, 3)
    assert len(waits) == 2


def test_backoff_does_not_swallow_other_errors(fetch):
    with pytest.raises(KeyError):
        fetch.with_backoff("x", lambda: {}["a"], sleep=lambda s: None)


def write_repositories(path: Path, rows):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    con.execute("CREATE TABLE r(repo_id VARCHAR, license_type VARCHAR, num_sessions BIGINT)")
    con.executemany("INSERT INTO r VALUES (?,?,?)", rows)
    con.execute(f"COPY r TO '{path / 'repositories.parquet'}' (FORMAT PARQUET)")


def test_first_repo_must_be_permissive(fetch, tmp_path):
    write_repositories(tmp_path, [(fetch.FIRST_REPO, "AGPL-3.0", 9), ("a/b", "MIT", 5)])
    with pytest.raises(SystemExit, match="not permissively licensed"):
        fetch.selected_repos(tmp_path)


def test_selection_puts_first_repo_then_busiest_permissive(fetch, tmp_path):
    rows = [(fetch.FIRST_REPO, "MIT", 1), ("a/b", "MIT", 5), ("c/d", "GPL-3.0", 99)]
    write_repositories(tmp_path, rows)
    assert fetch.selected_repos(tmp_path) == [fetch.FIRST_REPO, "a/b"]


def make_source(path: Path, rows):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    con.execute("CREATE TABLE c(repo_id VARCHAR, content VARCHAR)")
    con.executemany("INSERT INTO c VALUES (?,?)", rows)
    con.execute(f"COPY c TO '{path}' (FORMAT PARQUET)")


def fake_fetch():
    def fetch_file(dataset, name, repo_type, token, local_dir, revision):
        target = Path(local_dir) / name
        make_source(target, [("a/b", "synthetic")])
        return str(target)

    return fetch_file


def test_export_removes_stage_and_partials_on_failure(fetch, tmp_path, monkeypatch):
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setattr(fetch, "hf_fetch", fake_fetch)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(duckdb.Error):
        fetch.export_table(dest, "rev", "conversations", ["a/b"], "nonexistent_col")
    assert not (dest / ".staging").exists()
    assert list((dest / "conversations").iterdir()) == []


def test_export_success_leaves_only_slices(fetch, tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setattr(fetch, "hf_fetch", fake_fetch)
    fetch.export_table(tmp_path, "rev", "conversations", ["a/b"], "*")
    assert not (tmp_path / ".staging").exists()
    assert (tmp_path / "conversations" / "a__b.parquet").exists()


def test_secure_tree_tightens_existing_modes(fetch, tmp_path):
    (tmp_path / "sub").mkdir(mode=0o755)
    f = tmp_path / "sub" / "x.parquet"
    f.write_text("x")
    f.chmod(0o644)
    fetch.secure_tree(tmp_path)
    assert (tmp_path.stat().st_mode & 0o777, (tmp_path / "sub").stat().st_mode & 0o777) == (
        0o700,
        0o700,
    )
    assert f.stat().st_mode & 0o777 == 0o600


def test_revision_resolved_once_and_pinned(fetch, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "fake")
    calls = []

    class Api:
        def __init__(self, token):
            pass

        def dataset_info(self, name):
            calls.append(name)
            return type("I", (), {"sha": "abc123"})()

    monkeypatch.setattr(fetch, "hf_api", lambda: Api(None))
    assert fetch.pinned_revision(tmp_path, None) == "abc123"
    assert fetch.pinned_revision(tmp_path, None) == "abc123"
    assert len(calls) == 1
    with pytest.raises(SystemExit, match="conflicts"):
        fetch.pinned_revision(tmp_path, "other")


def test_dest_outside_git_must_be_absolute(fetch, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert fetch.check_dest(tmp_path / "d") == tmp_path / "d"
    with pytest.raises(SystemExit, match="absolute"):
        fetch.check_dest(Path("rel"))


@pytest.mark.periphery
def test_dest_inside_repo_must_be_ignored_data(fetch, tmp_path):
    # A hook's GIT_DIR would make `git init` rewrite the real repo's config.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=fetch.clean_git_env())
    (tmp_path / ".gitignore").write_text("data/\n")
    assert fetch.check_dest(tmp_path / "data" / "swe-chat")
    with pytest.raises(SystemExit, match="git-ignored data"):
        fetch.check_dest(tmp_path / "notes")
    with pytest.raises(SystemExit, match="git-ignored data"):
        fetch.check_dest(tmp_path / "other" / "data")


class Resp:
    def __init__(self, retry_after):
        self.headers = {"Retry-After": retry_after}
        self.status_code = 429


def limited_with(retry_after):
    exc = LimitedError()
    exc.response = Resp(retry_after)
    return exc


def test_retry_after_hint_above_cap_fails_loudly(fetch):
    with pytest.raises(fetch.RateLimitExhaustedError, match="above the 300s cap"):
        fetch.retry_after_seconds(limited_with("99999"), 0)


def test_retry_after_hint_within_cap_is_honoured(fetch):
    assert fetch.retry_after_seconds(limited_with("120"), 0) == 120


@pytest.mark.parametrize("raw", ["soon", "nan", "inf", "-inf", "-5"])
def test_malformed_retry_after_is_reported_not_silent(fetch, capsys, raw):
    assert fetch.retry_after_seconds(limited_with(raw), 0) == fetch.RATE_LIMIT_BASE_SECONDS
    assert "malformed Retry-After" in capsys.readouterr().err


def test_failed_commits_export_removes_conversation_slices(fetch, tmp_path, monkeypatch):
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.setenv("HF_TOKEN", "fake")
    write_repositories(tmp_path, [(fetch.FIRST_REPO, "MIT", 1)])

    fetched = []

    def fetch_file(dataset, name, repo_type, token, local_dir, revision):
        fetched.append(name)
        target = Path(local_dir) / name
        con = duckdb.connect()
        con.execute("CREATE TABLE c(repo_id VARCHAR, content VARCHAR)")
        con.execute(f"INSERT INTO c VALUES ('{fetch.FIRST_REPO}', 'synthetic')")
        con.execute(f"COPY c TO '{target}' (FORMAT PARQUET)")  # no patch column
        return str(target)

    monkeypatch.setattr(fetch, "hf_fetch", lambda: fetch_file)
    with pytest.raises(duckdb.Error):
        fetch.cmd_export(tmp_path, "rev")
    assert fetched == ["conversations.parquet", "commits.parquet"]
    assert list((tmp_path / "conversations").iterdir()) == []
    assert not (tmp_path / ".staging").exists()


class Probe:
    def __init__(self, returncode, stderr):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ""


def test_unrecognised_git_failure_refuses(fetch, tmp_path, monkeypatch):
    err = "fatal: detected dubious ownership in repository at '/x'"
    monkeypatch.setattr(fetch.subprocess, "run", lambda *a, **k: Probe(128, err))
    with pytest.raises(SystemExit, match="dubious ownership"):
        fetch.check_dest(tmp_path / "d")


def test_not_a_git_repository_is_the_only_outside_case(fetch, tmp_path, monkeypatch):
    err = "fatal: not a git repository (or any of the parent directories): .git"
    monkeypatch.setattr(fetch.subprocess, "run", lambda *a, **k: Probe(128, err))
    assert fetch.check_dest(tmp_path / "d") == tmp_path / "d"
