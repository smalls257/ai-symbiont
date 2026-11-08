"""The `reviews` snapshot: what reviewers flagged, grouped by shared words, dismissals that stick.

Failures guarded against: Paper Tiger (530 near-identical review lessons shown one by one),
Silent Fallback (a dismissed group coming back under a new key after a re-mine, a credential in
a quote) and Black Box (a group that cannot be traced to the session step it came from).
"""

import time
from datetime import date

from review_builders import NULLS, OTHER, flag
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.service.review_view import review_member_refs, reviews_snapshot
from symbiont.service.rule_view import Triaged

SECRET = "abcd1234" + "efgh5678"  # built at runtime so no secret scanner reads a literal
DATES = {"s1": date(2026, 1, 1), "s2": date(2026, 2, 1), "s3": date(2026, 3, 1)}


NONE = Triaged()


def snapshot(lessons, triaged=NONE):
    return reviews_snapshot(lessons, DATES, triaged)


def test_comments_sharing_distinctive_words_form_one_group_with_everything_it_stands_for():
    (group,) = snapshot(NULLS)["groups"]
    assert group["count"] == 2 and group["sessions"] == 2
    assert group["gist"] == "Empty batch causes a null dereference"
    assert group["reviewers"] == ["CodeRabbit", "Copilot"]
    assert group["files"] == ["src/batch.ts", "src/queue.ts"]
    assert group["fixedBy"] == ["batch.ts"]
    assert len(group["lessonIds"]) == 2
    assert group["key"].startswith("review:") and "src/batch.ts" in group["key"]


def test_examples_link_back_to_the_session_step_newest_first():
    (group,) = snapshot(NULLS)["groups"]
    first = group["examples"][0]
    assert (first["sessionId"], first["step"], first["file"]) == ("s2", 4, "src/queue.ts")
    assert first["date"] == "2026-02-01" and "null dereference" in first["gist"]


def test_groups_are_listed_by_sessions_then_count_and_a_single_comment_is_its_own_group():
    same_session = [
        flag("s3", 7, "Unchecked cache eviction race", path="src/c1.ts"),
        flag("s3", 8, "Cache eviction race is unchecked", path="src/c2.ts"),
        flag("s3", 9, "Race in cache eviction unchecked", path="src/c3.ts"),
    ]
    groups = snapshot([OTHER, *same_session, *NULLS])["groups"]
    assert [(g["sessions"], g["count"]) for g in groups] == [(2, 2), (1, 3), (1, 1)]
    assert groups[2]["gist"] == "Rename the retry timeout constant"


def test_the_headline_gist_prefers_a_complete_sentence_over_a_dangling_fragment():
    fragment = flag("s1", 1, "Possible null dereference (`| 22", path="src/a.ts")
    whole = flag(
        "s2", 2, "A null dereference is possible when the batch is empty.", path="src/b.ts"
    )
    (group,) = snapshot([fragment, whole])["groups"]
    assert group["gist"] == "A null dereference is possible when the batch is empty."


def test_without_a_complete_sentence_the_shortest_gist_is_the_headline():
    (group,) = snapshot(NULLS)["groups"]
    assert group["gist"] == "Empty batch causes a null dereference"


def test_a_dismissed_rule_with_the_same_message_refs_does_not_hide_a_review_group():
    rule_members = {"rule:s1:3": frozenset({("s1", 3), ("s2", 4)})}
    shown = snapshot(NULLS, Triaged(dismissed=["rule:s1:3"], members=rule_members))
    assert [g["count"] for g in shown["groups"]] == [2]


def test_a_dismissed_group_is_left_out_and_counted():
    key = snapshot(NULLS)["groups"][0]["key"]
    shown = snapshot([OTHER, *NULLS], Triaged(dismissed=[key]))
    assert [g["count"] for g in shown["groups"]] == [1]
    assert shown["dismissed"] == 1


def test_a_dismissal_survives_a_re_mine_that_renames_the_group():
    earlier = {"review:old-key": frozenset({("s1", 3), ("s2", 4)})}
    shown = snapshot(NULLS, Triaged(dismissed=["review:old-key"], members=earlier))
    assert shown["groups"] == [] and shown["dismissed"] == 1


def test_one_shared_member_does_not_carry_a_dismissal_to_an_unrelated_group():
    earlier = {"review:old-key": frozenset({("s3", 1)})}
    shown = snapshot([OTHER, *NULLS], Triaged(dismissed=["review:old-key"], members=earlier))
    assert [g["count"] for g in shown["groups"]] == [2]


def test_other_signals_and_keys_without_a_gist_are_not_review_groups():
    odd = flag("s1", 9, "")
    failed = Lesson(
        PainPoint(Signature(Signal.FAILED_COMMAND, ("pytest", "t.py", "E")), "s1", 1, (("s1", 1),)),
        "",
        (),
        None,
        True,
        (("s1", 1),),
    )
    assert snapshot([odd, failed])["groups"] == []


def test_a_credential_in_a_gist_never_reaches_the_snapshot():
    leaky = flag("s1", 1, f"Remove the hardcoded token={SECRET} from config")
    assert SECRET not in str(snapshot([leaky]))


def test_member_refs_name_the_comments_a_group_stands_for_and_nothing_for_an_unknown_key():
    key = snapshot(NULLS)["groups"][0]["key"]
    assert review_member_refs(NULLS, key) == (("s1", 3), ("s2", 4))
    assert review_member_refs(NULLS, "review:none") == ()


def test_six_hundred_comments_group_well_under_a_second():
    many = [flag(f"s{i}", 1, f"Missing check number{i % 40} widget{i}") for i in range(600)]
    started = time.perf_counter()
    snapshot(many)
    assert time.perf_counter() - started < 1.0
