import json
from pathlib import Path

import pytest

from symbiont.delivery.hooks import HookEvent, observe_body
from symbiont.delivery.project_identity import (
    RegistryUnreadableError,
    git_root,
    known_projects,
    project_for,
)

KNOWN = frozenset({"repo"})


def root_at(path):
    return lambda start: Path(path)


def test_a_known_cwd_keeps_its_own_name():
    assert project_for("/w/repo/src", "p", frozenset({"src", "repo"}), root_at("/w/repo")) == "src"


def test_an_unknown_subdirectory_resolves_to_a_known_git_root():
    assert project_for("/w/repo/src/pkg", "p", KNOWN, root_at("/w/repo")) == "repo"


def test_an_unknown_root_leaves_the_cwd_name():
    assert project_for("/w/other/src", "p", KNOWN, root_at("/w/other")) == "src"


def test_no_git_root_leaves_the_cwd_name():
    assert project_for("/w/repo/src", "p", KNOWN, lambda start: None) == "src"


def test_nothing_known_changes_nothing_and_never_looks_for_a_root():
    def explode(start):
        raise AssertionError("the root must not be searched")

    assert project_for("/w/repo/src", "p", frozenset(), explode) == "src"


def test_no_cwd_uses_the_fallback():
    assert project_for(None, "p", KNOWN) == "p"


def test_git_root_finds_the_nearest_dot_git(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "a" / "b").mkdir(parents=True)
    assert git_root(tmp_path / "a" / "b") == tmp_path


def test_known_projects_reads_the_registry_and_an_absent_one_is_empty(tmp_path):
    assert known_projects(tmp_path) == frozenset()
    (tmp_path / "repos.json").write_text(json.dumps({"projects": {"repo": {"stance": "given"}}}))
    assert known_projects(tmp_path) == {"repo"}


def test_a_broken_registry_raises_naming_the_file(tmp_path):
    (tmp_path / "repos.json").write_text("{not json")
    with pytest.raises(RegistryUnreadableError, match="repos.json"):
        known_projects(tmp_path)


def test_observe_body_uses_the_known_root_for_a_claude_code_subdirectory(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    data = {"session_id": "s", "cwd": str(root / "src"), "prompt": "hi"}
    body = observe_body(HookEvent.USER_PROMPT_SUBMIT, data, "claude_code", "p", KNOWN)
    assert body["payload"]["record"]["project"] == "repo"
    plain = observe_body(HookEvent.USER_PROMPT_SUBMIT, data, "muse_code", "p")
    assert plain["payload"]["record"]["project"] == "src"
