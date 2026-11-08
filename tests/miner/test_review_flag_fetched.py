import json

from record_builders import edit, run, say, session
from symbiont.miner.mine import mine_chain
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.review_flag import find_review_flags

FETCH = "gh api repos/o/r/pulls/3/comments"
GIST = "Batch delete publishes once per item — batch it."
MAJOR = f"_⚠️ Potential issue_ | _🟠 Major_\n\n**{GIST}**\n\nEach iteration publishes."
NIT = "_🧹 Nitpick_ | _🔵 Trivial_\n\n**Rename the local.**"


def _comments(body=MAJOR, comment_id=11, path="src/batch.ts"):
    return json.dumps(
        [{"id": comment_id, "user": {"login": "coderabbitai[bot]"}, "body": body, "path": path}]
    )


def _fetch(**fields):
    return run(FETCH, output=_comments(**fields))


def test_fetched_comment_then_edit_of_its_file_is_one_flag():
    s = session(_fetch(), edit("src/batch.ts"))
    assert find_review_flags(s) == [
        PainPoint(
            Signature(Signal.REVIEW_FLAG, ("src/batch.ts", "CodeRabbit", GIST)),
            "s1",
            0,
            (("s1", 0), ("s1", 1)),
        )
    ]


def test_same_comment_fetched_three_times_is_one_flag():
    s = session(_fetch(), _fetch(), _fetch(), edit("src/batch.ts"))
    assert len(find_review_flags(s)) == 1


def test_no_later_edit_of_the_path_is_no_flag():
    s = session(_fetch(), edit("src/other.ts"))
    assert find_review_flags(s) == []
    assert find_review_flags(session(edit("src/batch.ts"), _fetch())) == []


def test_a_nitpick_is_no_flag():
    s = session(_fetch(body=NIT), edit("src/batch.ts"))
    assert find_review_flags(s) == []


def test_the_agents_own_posted_text_is_no_flag():
    posted = run(f"gh api repos/o/r/issues/3/comments -f body='{MAJOR}'")
    s = session(posted, _fetch(), edit("src/batch.ts"))
    assert find_review_flags(s) == []


def test_absolute_edit_path_matches_a_relative_comment_path():
    s = session(_fetch(), edit("/work/repo/src/batch.ts"))
    assert len(find_review_flags(s)) == 1


def test_a_later_mention_of_the_comment_text_does_not_hide_it():
    s = session(_fetch(), say("on it"), edit("src/batch.ts"), run(f"echo '{MAJOR}'"))
    assert len(find_review_flags(s)) == 1


def test_chain_keeps_the_first_sighting_of_a_signature():
    one = session(_fetch(comment_id=11), edit("src/batch.ts"))
    two = [
        r.__class__(**{**r.__dict__, "session_id": "s2"})
        for r in session(_fetch(comment_id="PRRC_node"), edit("src/batch.ts"))
    ]
    found = mine_chain([one, two], {})
    flags = [p for p in found if p.signature.signal is Signal.REVIEW_FLAG]
    assert [p.session_id for p in flags] == ["s1"]
