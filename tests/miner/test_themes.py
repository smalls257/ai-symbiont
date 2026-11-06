"""Themes: what was being worked on, in the codebase's own words."""

from record_builders import edit, session, user
from symbiont.miner.themes import (
    Codebase,
    codebase_vocabulary,
    task_text,
    themes_of,
)
from symbiont.records.session_tags import branch_tag, title_tag

CODE = Codebase(frozenset({"app"}))


def defining(path, name):
    return edit(path, diff=f"--- a/{path}\n+++ b/{path}\n+def {name}(x):\n+    pass\n")


def test_codebase_decides_inside_by_the_one_repo_relative_rule():
    assert CODE.contains("app/parser.py") and CODE.contains("/work/app/lib/x.py")
    assert not CODE.contains("/tmp/scratch.py") and not CODE.contains("notes.py")


def test_the_vocabulary_is_file_stems_and_name_parts_seen_five_times_without_generic_words():
    edits = [defining("app/tokenizer.py", "split_window_frame") for _ in range(5)]
    edits += [defining("app/rare.py", "once") for _ in range(2)]
    words = codebase_vocabulary([session(*edits)], CODE)
    assert {"tokenizer", "split", "window", "frame"} <= words
    assert "rare" not in words
    outside = [defining("/tmp/scratch_tokens.py", "split_scratch") for _ in range(9)]
    assert "scratch" not in codebase_vocabulary([session(*outside)], CODE)
    generic = [defining("app/data_values.py", "check_value") for _ in range(9)]
    assert not {"data", "values", "check"} & codebase_vocabulary([session(*generic)], CODE)


def test_themes_come_only_from_the_codebase_vocabulary():
    text = "The official reference says the window parser drops a frame."
    assert themes_of(text, frozenset({"window", "parser", "frame"})) == {
        "window",
        "parser",
        "frame",
    }
    assert themes_of(text, frozenset({"tokenizer"})) == set()


def test_pasted_code_does_not_make_themes():
    text = "Fix the parser.\n```\nSELECT window FROM t\n```"
    assert themes_of(text, frozenset({"window", "parser"})) == {"parser"}


def test_the_issue_body_is_the_task_text_when_there_is_one():
    body = "<issue_description>The window frame is wrong</issue_description> template noise"
    assert task_text(session(user("hello " + body))) == "The window frame is wrong"


def test_a_claude_code_session_takes_its_title_and_branch_as_theme_text():
    tagged = user("please help", tags=(title_tag("Fix tokenizer crash"), branch_tag("fix-window")))
    text = task_text(session(tagged))
    assert themes_of(text, frozenset({"tokenizer", "window"})) == {"tokenizer", "window"}
    assert themes_of(task_text(session(user("please help"))), frozenset({"tokenizer"})) == set()
