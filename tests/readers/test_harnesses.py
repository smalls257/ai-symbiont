"""The harness registry is the one place that knows which harnesses exist.

Violation prevented: Distributed Monolith (eleven files that each branch on a harness name) and
Silent Fallback (a hook that guesses Claude Code when nothing says which harness it runs under).
"""

import pytest

from symbiont.delivery.hook_profiles import PROFILES
from symbiont.readers import READERS
from symbiont.readers.harnesses import (
    HARNESSES,
    UnknownHarnessError,
    detect,
    harness,
    harness_for_reader,
    labels_and,
    labels_or,
)


def test_every_harness_has_a_reader_and_a_hook_profile():
    assert {h.id for h in HARNESSES} == set(PROFILES)
    assert all(h.reader in READERS for h in HARNESSES)


def test_muse_is_detected_before_claude_code_because_it_sets_both_markers():
    both = {"MUSE_PLUGIN_ROOT": "/m", "CLAUDE_PLUGIN_ROOT": "/c", "CLAUDECODE": "1"}

    assert detect(both).id == "muse_code"
    assert detect({"CLAUDE_PLUGIN_ROOT": "/c"}).id == "claude_code"
    assert detect({"CLAUDECODE": "1"}).id == "claude_code"


def test_no_marker_detects_nothing():
    assert detect({}) is None
    assert detect({"PATH": "/usr/bin"}) is None


def test_an_unknown_id_names_itself_and_the_known_ones():
    with pytest.raises(UnknownHarnessError, match="nope.*muse_code, claude_code"):
        harness("nope")


def test_a_reader_name_maps_back_to_its_harness_id():
    assert harness_for_reader("muse-code") == "muse_code"
    assert harness_for_reader("claude-code") == "claude_code"
    assert harness_for_reader("openhands") is None


def test_labels_read_as_prose_from_the_registry():
    assert labels_and() == "Claude Code and Muse Code"
    assert labels_or() == "Claude Code or Muse Code"
