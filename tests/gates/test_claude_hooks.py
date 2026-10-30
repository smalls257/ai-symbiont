"""The Claude Code hooks block what the project rules forbid and report lint failures to the
agent (exit 2 with the finding on stderr), instead of swallowing them."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"

pytestmark = pytest.mark.periphery


def _run(hook: str, payload: dict, *, cwd: Path = REPO, project_dir: Path = REPO):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        ["bash", str(HOOKS / hook)],
        input=json.dumps(payload),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path: str) -> dict:
    return {"tool_input": {"file_path": str(REPO / path)}}


def _bash(command: str) -> dict:
    return {"tool_input": {"command": command}}


@pytest.mark.parametrize(
    "path",
    [
        "data/x.jsonl",
        "runs/a/events.jsonl",
        ".env",
        "src/.env.local",
        "id.key",
        ".claude/settings.json",
        ".claude/hooks/guard_git.sh",
        ".lizard-whitelist.txt",
        ".naming-waivers.txt",
        "scripts/gates/test-floor.txt",
        "scripts/gates/run.sh",
        "scripts/hooks/pre-commit",
        ".gitleaks.toml",
        ".gitleaks-baseline.json",
        ".semgrep/symbiont/structure.yaml",
        ".importlinter",
    ],
)
def test_path_guard_denies_data_secrets_harness_and_waivers(path):
    out = _run("guard_paths.sh", _write(path))
    assert out.returncode == 2 and "QG-AI-02" in out.stderr


def test_path_guard_denies_the_owners_global_claude_dir():
    out = _run("guard_paths.sh", {"tool_input": {"file_path": str(Path.home() / ".claude" / "x")}})
    assert out.returncode == 2


@pytest.mark.parametrize("path", ["src/symbiont/core/a.py", "docs/a.md", "tests/data_loader.py"])
def test_path_guard_allows_ordinary_work(path):
    assert _run("guard_paths.sh", _write(path)).returncode == 0


def _repo_at(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True, capture_output=True)
    return path


def test_a_worktree_under_dot_claude_is_judged_against_its_own_root(tmp_path):
    # CLAUDE_PROJECT_DIR deliberately points elsewhere: the edited file's own toplevel wins
    root = _repo_at(tmp_path / ".claude" / "worktrees" / "agent-x")
    ok = {"tool_input": {"file_path": str(root / "src" / "new_dir" / "a.py")}}
    bad = {"tool_input": {"file_path": str(root / "data" / "rows.csv")}}
    assert _run("guard_paths.sh", ok, project_dir=REPO).returncode == 0
    assert _run("guard_paths.sh", bad, project_dir=REPO).returncode == 2


def test_a_frozen_prereg_cannot_be_edited_but_a_draft_can(tmp_path):
    root = _repo_at(tmp_path / "repo")
    (root / "prereg").mkdir()
    frozen, draft = root / "prereg" / "f.md", root / "prereg" / "d.md"
    frozen.write_text("Status: FROZEN\n")
    draft.write_text("Status: DRAFT\n")
    deny = _run("guard_paths.sh", {"tool_input": {"file_path": str(frozen)}})
    allow = _run("guard_paths.sh", {"tool_input": {"file_path": str(draft)}})
    assert deny.returncode == 2 and allow.returncode == 0


def test_a_notebook_edit_is_guarded_by_its_notebook_path(tmp_path):
    root = _repo_at(tmp_path / "repo")
    payload = {"tool_input": {"notebook_path": str(root / "data" / "n.ipynb")}}
    assert _run("guard_paths.sh", payload).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "git stash",
        "git commit --amend -m x",
        "cd x && git reset --hard",
        "git rebase main",
        "git push --force origin main",
        "git push -f",
        "git add -A",
        "git add .",
        "git -C /tmp/r stash pop",
        "git --no-pager stash",
        "git -c user.name=x stash",
    ],
)
def test_git_guard_blocks_history_rewrites(command):
    out = _run("guard_git.sh", _bash(command))
    assert out.returncode == 2 and "project git rules" in out.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git add src/a.py tests/test_a.py",
        "git commit -m 'why'",
        "git status",
        "git diff --cached",
        "grep -n 'git stash' notes.md",
        "echo never git reset here",
        "git log --oneline",
    ],
)
def test_git_guard_allows_explicit_paths_and_mentions(command):
    assert _run("guard_git.sh", _bash(command)).returncode == 0


def test_agents_in_a_worktree_may_not_push_but_the_owner_may(tmp_path):
    worktree = tmp_path / ".claude" / "worktrees" / "agent-x"
    checkout = tmp_path / "checkout"
    worktree.mkdir(parents=True)
    checkout.mkdir()
    owner = _run("guard_git.sh", _bash("git push origin main"), cwd=checkout)
    agent = _run("guard_git.sh", _bash("git push origin main"), cwd=worktree)
    assert owner.returncode == 0 and agent.returncode == 2


def test_lint_hook_reports_a_finding_with_exit_2():
    bad = REPO / "scripts" / "gates" / "_hook_probe.py"
    bad.write_text("import os\n")
    try:
        out = _run("lint_edited_file.sh", {"tool_input": {"file_path": str(bad)}})
    finally:
        bad.unlink()
    assert out.returncode == 2
    assert "F401" in out.stderr and "QG-AI-01" in out.stderr


def test_lint_hook_is_silent_on_a_clean_file_and_ignores_non_python():
    clean = _run("lint_edited_file.sh", _write("scripts/gates/check_nesting.py"))
    assert clean.returncode == 0 and clean.stderr == ""
    assert _run("lint_edited_file.sh", _write("docs/a.md")).returncode == 0


def _write_text(path: str, content: str) -> dict:
    return {"tool_input": {"file_path": str(REPO / path), "content": content}}


@pytest.mark.parametrize(
    "content",
    [
        "host = '" + "192.168." + "1.20'\n",
        "cache = '/Users/" + "alice" + "/work'\n",
        "token = 'hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7" + "'\n",
        "contact = 'real.person@" + "gmail.com'\n",
    ],
)
def test_edit_time_guard_denies_secrets_and_private_infrastructure(content):
    out = _run("guard_paths.sh", _write_text("src/symbiont/a.py", content))
    assert out.returncode == 2 and "QG-SEC-06" in out.stderr


def test_edit_time_guard_scans_edit_and_multiedit_text():
    leak = "ip = '" + "10." + "1.2.3'"
    edit = {"tool_input": {"file_path": str(REPO / "src" / "a.py"), "new_string": leak}}
    multi = {
        "tool_input": {"file_path": str(REPO / "src" / "a.py"), "edits": [{"new_string": leak}]}
    }
    assert _run("guard_paths.sh", edit).returncode == 2
    assert _run("guard_paths.sh", multi).returncode == 2


def test_edit_time_guard_allows_clean_text_and_placeholders():
    clean = "url = 'http://127.0.0.1:8081'\nmail = 'user@example.com'\npath = '/Users/you/x'\n"
    assert _run("guard_paths.sh", _write_text("src/symbiont/a.py", clean)).returncode == 0


@pytest.mark.parametrize("path", ["lora/model.safetensors", "w.pt", "d.wad", "k.pem", "dump.jsonl"])
def test_edit_time_guard_denies_weights_datasets_and_keys_by_name(path):
    out = _run("guard_paths.sh", _write(path))
    assert out.returncode == 2 and "QG-SEC-06" in out.stderr


def test_edit_time_guard_allows_a_fixture_jsonl_and_a_results_file():
    assert _run("guard_paths.sh", _write("tests/fixtures/a.jsonl")).returncode == 0
    assert _run("guard_paths.sh", _write("results/a.json")).returncode == 0


def test_edit_time_guard_protects_the_publish_check():
    assert _run("guard_paths.sh", _write("scripts/publish/check_export.sh")).returncode == 2
