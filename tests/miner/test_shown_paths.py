"""Paths in notes: no home directory, no user name, device paths whole."""

from symbiont.miner.incident_words import said_line
from symbiont.miner.shown_paths import plain_paths


def test_a_home_path_is_cut_to_its_file_name():
    assert plain_paths("see /home/dev/Projects/lab/improvement-queue") == "see improvement-queue"


def test_a_device_path_stays_whole():
    assert plain_paths("lsof -ti :3000 | xargs kill 2>/dev/null") == (
        "lsof -ti :3000 | xargs kill 2>/dev/null"
    )


def test_a_quoted_message_names_no_home_directory():
    said = said_line("fix these issues: /home/dev/Projects/skills/queue. use one commit", 160)
    assert said == "fix these issues: queue. use one commit"
