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


def _flags_for(comment_path, *edited):
    s = session(_fetch(path=comment_path), *[edit(f) for f in edited])
    return find_review_flags(s)


def test_a_path_matches_only_on_a_directory_boundary():
    assert _flags_for("a/b.ts", "xa/b.ts") == []
    assert _flags_for("b.ts", "a/xb.ts") == []
    assert len(_flags_for("a/b.ts", "/work/repo/a/b.ts")) == 1
    assert len(_flags_for("a/b.ts", "a/b.ts")) == 1


def test_a_bare_file_name_matches_only_the_one_edited_file_of_that_name():
    assert len(_flags_for("index.ts", "index.ts")) == 1
    assert len(_flags_for("index.ts", "src/web/index.ts")) == 1
    assert _flags_for("index.ts", "src/web/index.ts", "src/api/index.ts") == []


def test_a_short_body_is_never_taken_for_the_agents_own_text():
    short = "Rename it."
    s = session(run(f"echo {short}"), _fetch(body=short), edit("src/batch.ts"))
    assert len(find_review_flags(s)) == 1


def test_finding_flags_among_megabytes_of_earlier_commands_is_fast():
    import time

    filler = [run("echo " + "x " * 500) for _ in range(4000)]
    fetches = [_fetch(comment_id=i, body=MAJOR + f" {i}") for i in range(200)]
    s = session(*filler, *fetches, edit("src/batch.ts"))
    started = time.perf_counter()
    assert len(find_review_flags(s)) == 200
    assert time.perf_counter() - started < 0.5


def test_hunk_flags_dedupe_by_signature_across_a_chain():
    from record_builders import replace_text, review

    hunk = "@@ -1,1 +1,2 @@\n+return None\n"
    one = session(review("a.py", hunk, "Do not swallow."), replace_text("a.py", "return None", ""))
    two = [
        r.__class__(**{**r.__dict__, "session_id": "s2"})
        for r in session(
            review("a.py", hunk, "Do not swallow."), replace_text("a.py", "return None", "")
        )
    ]
    flags = [p for p in mine_chain([one, two], {}) if p.signature.signal is Signal.REVIEW_FLAG]
    assert [p.session_id for p in flags] == ["s1"]
