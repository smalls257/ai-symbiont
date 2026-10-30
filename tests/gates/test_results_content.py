"""QG-SEC-04: published json holds counts, ids and labels only (Leaky Narrative at the boundary)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gate_loader import load_gate

content = load_gate("check_results_content")
REPO = Path(__file__).resolve().parents[2]


def test_counts_ids_and_labels_pass():
    document = {
        "n_runs": 12,
        "prompt_tokens": 4000,
        "patch_applied": True,
        "rows": [{"arm": "counters", "role": "floor", "ids": ["tobymao__sqlglot-4001"]}],
        "rule": "keep tasks whose gold diff changes at most forty lines",
    }
    assert content.findings_in("r.json", document) == []


@pytest.mark.parametrize(
    "key",
    [
        "prompt", "content", "messages", "patch", "trajectory", "Transcript", "completion", "diff",
        "problem_statement", "response", "output", "input", "reply", "summary", "comment",
        "command", "question", "answer", "query",
    ],
)  # fmt: skip
def test_a_field_named_for_text_fires_at_any_depth_when_it_holds_a_sentence(key):
    found = content.findings_in("r.json", {"rows": [{"deep": {key: "fix the failing join"}}]})
    assert any(key.lower() in line.lower() and "holds text" in line for line in found)


def test_a_text_named_field_holding_a_number_or_a_setting_word_passes():
    assert content.findings_in("r.json", {"reasoning": "low", "output": 3, "input": None}) == []


@pytest.mark.parametrize(
    "document",
    [
        {"title": "the planner rewrote the join after the user said it was wrong again"},
        {"x": "short sentence under an unlisted key that is still thirteen words long here"},
        {"rows": [{"problem_statement": "Fix bug"}]},
        {"response": "Sure, here is the patch"},
        {"output": "ok done"},
    ],
)
def test_short_real_sentences_under_unlisted_keys_fail(document):
    assert content.findings_in("r.json", document) != []


@pytest.mark.parametrize("document", ["just a string", ["a", "b"], 42, None])
def test_the_top_level_must_be_an_object(document):
    found = content.findings_in("r.json", document)
    assert len(found) == 1 and "not an object" in found[0]


def test_a_long_string_fires_and_a_long_token_does_not():
    assert content.findings_in("r.json", {"note_x": "a b " * 60}) != []
    assert content.findings_in("r.json", {"flags": "01" * 100}) == []
    assert content.findings_in("r.json", {"hash": "a" * (content.MAX_TOKEN_CHARS + 1)}) != []


def test_label_fields_may_hold_a_sentence_but_not_a_blob_or_a_newline():
    sentence = "under test, seed-averaged over wiring seeds zero to two (the row the rule uses)"
    assert (
        content.findings_in("r.json", {"rows": [{"label": sentence}], "caveats": [sentence]}) == []
    )
    assert content.findings_in("r.json", {"label": "word " * 80}) != []
    assert content.findings_in("r.json", {"label": "a b\nc"}) != []
    assert content.findings_in("r.json", {"run_note": sentence}) == []


def test_a_newline_blob_fires_even_when_short():
    found = content.findings_in("r.json", {"table": "| a | b |\n| 1 | 2 |"})
    assert len(found) == 1 and "newline" in found[0]


def test_object_keys_obey_the_same_limits():
    assert content.findings_in("r.json", {"word " * 60: 1}) != []
    assert (
        content.findings_in("r.json", {"fly seed 0": 1, "balanced accuracy (AUROC of the flag)": 2})
        == []
    )


def test_the_cli_exits_one_on_a_finding_and_two_on_an_unreadable_file(tmp_path):
    bad, broken = tmp_path / "bad.json", tmp_path / "broken.json"
    bad.write_text(json.dumps({"prompt": "hello there friend"}))
    broken.write_text("{not json")
    script = str(REPO / "scripts" / "gates" / "check_results_content.py")

    def run(path):
        return subprocess.run([sys.executable, script, str(path)], capture_output=True, text=True)

    assert run(bad).returncode == 1
    assert run(broken).returncode == 2


def test_the_files_in_this_repo_are_clean():
    files = content.default_files(REPO)
    assert files, "no results files found: the check would pass on nothing"
    problems = [p for f in files for p in content.findings_in(f.name, json.loads(f.read_text()))]
    assert problems == []


def test_short_label_fields_keep_the_default_length_limit():
    twelve_plus = "under test, seed averaged over wiring seeds zero to two and then some more words"
    assert content.findings_in("r.json", {"label": twelve_plus, "status": twelve_plus}) == []
    for key in ("label", "status", "source"):
        found = content.findings_in("r.json", {key: "x " * 70})
        assert any("limit 120" in line for line in found), key


def test_long_label_fields_stop_at_two_hundred_sixty_characters():
    assert content.MAX_LABEL_CHARS == 260
    assert content.findings_in("r.json", {"rule": "word " * 51}) == []
    assert content.findings_in("r.json", {"rule": "word " * 53}) != []
    assert content.findings_in("r.json", {"caveats": ["word " * 53]}) != []


def test_the_number_of_sentence_length_strings_per_file_is_capped():
    sentence = "this caveat is a full sentence with more than twelve words in it, truly"
    ok = {"caveats": [sentence] * content.MAX_LONG_LABELS}
    too_many = {"caveats": [sentence] * (content.MAX_LONG_LABELS + 1)}
    assert content.findings_in("r.json", ok) == []
    found = content.findings_in("r.json", too_many)
    assert len(found) == 1 and "sentence-length strings" in found[0]
