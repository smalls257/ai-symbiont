"""The shell gates fail closed: a forbidden path, a missing config or a missing tool is a
non-zero exit, never a quiet pass. Each test builds a throwaway git repo so the real tree
is untouched and the gate is anchored to that repo's root, not to the cwd."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates"
SCRIPTS = ("lib.sh", "check_paths.sh", "check_complexity.sh", "check_secrets.sh")

pytestmark = pytest.mark.periphery


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts" / "gates").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy(GATES / name, root / "scripts" / "gates" / name)
    _git(root, "init", "-q", "-b", "main")
    return root


def _run(root: Path, script: str, *args: str, cwd: Path | None = None):
    return subprocess.run(
        ["bash", str(root / "scripts" / "gates" / script), *args],
        cwd=cwd or root,
        capture_output=True,
        text=True,
        check=False,
    )


def _track(root: Path, relpath: str, content: str = "x\n") -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(root, "add", relpath)


@pytest.mark.parametrize(
    "forbidden",
    [
        "data/rows.csv",
        "runs/a/events.jsonl",
        "notes/transcripts.md",
        "x.parquet",
        "m.gguf",
        "w.safetensors",
        "db.sqlite",
        ".env",
        "src/.env.local",
        "dump.jsonl",
        "m.bin",
        "w.pt",
        "lora/adapter_model.safetensors",
        "lora/adapter_config.json",
        "doom/freedoom2.wad",
        "keys/server.pem",
        "id_ed25519",
        "dumps/rows.csv",
        "agent.traj",
        "run.log",
        "notes/trajectories.md",
        "stray/config.json",
        "ARCHIVE.ZIP",
    ],
)
def test_path_guard_rejects_datasets_transcripts_weights_and_env(repo, forbidden):
    _track(repo, forbidden)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and forbidden in out.stderr


def test_path_guard_allows_synthetic_fixture_jsonl_and_ordinary_files(repo):
    _track(repo, "tests/fixtures/openhands/two.jsonl", '{"a": 1}\n')
    _track(repo, "src/a.py")
    assert _run(repo, "check_paths.sh").returncode == 0


def test_path_guard_rejects_an_oversized_fixture(repo):
    _track(repo, "tests/fixtures/big.jsonl", "x" * 200_001)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "big.jsonl" in out.stderr


def test_path_guard_is_anchored_to_the_repo_root_not_the_cwd(repo):
    _track(repo, "data/rows.csv")
    (repo / "docs").mkdir()
    assert _run(repo, "check_paths.sh", cwd=repo / "docs").returncode == 1


def test_complexity_gate_without_its_whitelist_is_an_error_not_a_pass(repo):
    _track(repo, "src/symbiont/core/a.py", "x = 1\n")
    out = _run(repo, "check_complexity.sh", "src/symbiont/core/a.py")
    assert out.returncode == 2 and "missing or empty config" in out.stderr


def test_secrets_gate_without_its_config_is_an_error_not_a_pass(repo):
    out = _run(repo, "check_secrets.sh", "files", "anything.txt")
    assert out.returncode == 2 and ".gitleaks.toml" in out.stderr


def test_gates_outside_a_git_tree_are_an_error(tmp_path):
    (tmp_path / "scripts" / "gates").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy(GATES / name, tmp_path / "scripts" / "gates" / name)
    out = _run(tmp_path, "check_paths.sh")
    assert out.returncode == 2 and "not inside a git work tree" in out.stderr


@pytest.mark.parametrize(
    "allowed",
    [
        "results/calibration.json",
        "dashboard/sample/coding.json",
        "tests/fixtures/openhands/two.json",
        ".claude/settings.json",
        ".gitleaks-baseline.json",
        "docs/logo.png",
        "src/symbiont/records/schema.py",
    ],
)
def test_path_guard_allows_counts_json_images_and_code(repo, allowed):
    _track(repo, allowed)
    assert _run(repo, "check_paths.sh").returncode == 0


def test_path_guard_rejects_a_file_over_one_megabyte(repo):
    _track(repo, "docs/big.txt", "x" * 1_048_577)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "big.txt" in out.stderr


def test_path_guard_allows_the_lockfile_over_one_megabyte(repo):
    _track(repo, "uv.lock", "x" * 1_048_577)
    assert _run(repo, "check_paths.sh").returncode == 0


def test_path_guard_rejects_a_binary_hidden_under_an_ordinary_name(repo):
    path = repo / "assets" / "notes.txt"
    path.parent.mkdir()
    path.write_bytes(bytes(range(256)) * 4)
    _git(repo, "add", "assets/notes.txt")
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "notes.txt" in out.stderr


def test_path_guard_tree_mode_judges_an_exported_directory(repo, tmp_path):
    tree = tmp_path / "export"
    (tree / "data").mkdir(parents=True)
    (tree / "data" / "rows.csv").write_text("a,b\n")
    (tree / "src").mkdir()
    (tree / "src" / "a.py").write_text("x = 1\n")
    bad = _run(repo, "check_paths.sh", "tree", str(tree))
    assert bad.returncode == 1 and "data/rows.csv" in bad.stderr
    (tree / "data" / "rows.csv").unlink()
    assert _run(repo, "check_paths.sh", "tree", str(tree)).returncode == 0


@pytest.mark.parametrize(
    "forbidden",
    [
        "donnée.parquet",
        "données.csv",
        "my data/rows.parquet",
        "résumé/trajectories.md",
        "weights.PEM",
        "DATA.CSV",
        "模型.safetensors",
    ],
)
def test_path_guard_sees_non_ascii_spaced_and_upper_case_names(repo, forbidden):
    _track(repo, forbidden)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and forbidden in out.stderr


def test_path_guard_measures_the_size_of_a_non_ascii_named_file(repo):
    _track(repo, "t/é.dat", "x" * 1_048_577)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "é.dat" in out.stderr


def test_path_guard_sees_a_binary_with_a_non_ascii_name(repo):
    path = repo / "t" / "ñ.txt"
    path.parent.mkdir()
    path.write_bytes(bytes(range(256)) * 4)
    _git(repo, "add", "t/ñ.txt")
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "ñ.txt" in out.stderr


@pytest.mark.parametrize(
    "name", ['quo"te.txt', "back\\slash.txt", "new\nline.txt", "tab\there.txt"]
)
def test_path_guard_refuses_names_it_cannot_check_safely(repo, name):
    _track(repo, name)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "cannot be checked safely" in out.stderr


def test_path_guard_allows_ordinary_non_ascii_and_spaced_names(repo):
    _track(repo, "docs/café notes.md")
    _track(repo, "src/données_utiles.py")
    assert _run(repo, "check_paths.sh").returncode == 0


@pytest.mark.parametrize("name", ["results/notes.txt", "results/dump.bin", "results/DUMP.TXT"])
def test_results_directory_holds_json_only(repo, name):
    _track(repo, name)
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and name in out.stderr


def test_a_name_that_contains_another_name_cannot_hide_it(repo):
    """The dedup must match whole names: staging 'a data/x.txt' first used to hide 'data/x.txt'."""
    _track(repo, "a data/x.txt")
    _track(repo, "data/x.txt")
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "\ndata/x.txt\n" in "\n" + out.stderr


def test_names_with_spaces_are_judged_one_by_one(repo):
    _track(repo, "ok dir/fine file.py")
    _track(repo, "my docs/secret data.parquet")
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and "my docs/secret data.parquet" in out.stderr
    assert "fine file.py" not in out.stderr


def test_a_file_both_tracked_and_staged_is_reported_once(repo):
    _track(repo, "data/x.csv")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x")
    (repo / "data" / "x.csv").write_text("changed\n")
    _git(repo, "add", "data/x.csv")
    out = _run(repo, "check_paths.sh")
    assert out.returncode == 1 and out.stderr.count("data/x.csv") == 1
