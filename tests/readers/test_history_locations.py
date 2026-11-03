"""Where past sessions live, on every platform, and what happens when the place is wrong.

Failure guarded against: Silent Fallback, a Windows (or misconfigured) path that matches no
sessions and reports "nothing to learn from" instead of saying where it looked.
"""

from pathlib import PureWindowsPath

from symbiont.readers.claude_code import project_folder_name, session_logs
from symbiont.readers.muse_code import muse_store_root


def test_claude_code_names_a_windows_repository_folder_by_the_same_rule():
    assert (
        project_folder_name(str(PureWindowsPath("C:/Users/user/my repo")))
        == "C--Users-user-my-repo"
    )


def test_claude_code_logs_are_found_under_the_home_folder(tmp_path):
    repo = tmp_path / "work" / "repo"
    repo.mkdir(parents=True)
    folder = tmp_path / "home" / ".claude" / "projects" / project_folder_name(str(repo.resolve()))
    folder.mkdir(parents=True)
    (folder / "a.jsonl").write_text("{}\n")

    assert session_logs(repo, tmp_path / "home") == [folder / "a.jsonl"]


def test_muse_code_data_defaults_to_local_share_under_the_home_folder(tmp_path):
    assert muse_store_root({}, tmp_path) == tmp_path / ".local" / "share"


def test_muse_code_data_follows_xdg_data_home_when_it_exists(tmp_path):
    assert muse_store_root({"XDG_DATA_HOME": str(tmp_path)}, tmp_path / "h") == tmp_path
