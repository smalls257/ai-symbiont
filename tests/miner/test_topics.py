"""A topic map must place every summarized, non-noise session exactly once.

Failure guarded against: Silent Fallback (a session that fell out of the map vanishes from the
dashboard with no signal) and Leaky Narrative (names that are sentences, not 2 to 4 words).
"""

import pytest

from symbiont.miner.session_summary import SessionSummary, SummaryError, summary_from
from symbiont.miner.topics import TopicMapError, topic_map_from


def summary(ident, noise=False):
    return SessionSummary(ident, "goal", "done", "", noise)


def request(**changes):
    base = {
        "topics": [
            {"name": "Auth and MFA", "description": "login work", "session_ids": ["a", "b"]},
            {"name": "Other", "description": "the rest", "session_ids": ["c"]},
        ],
        "frictions": [{"name": "Wrong branch", "description": "git mishaps", "session_ids": ["a"]}],
        "correction_groups": [
            {"name": "Back to main and pull", "description": "rebase asks", "refs": [["a", 3]]}
        ],
    }
    return base | changes


def test_a_complete_map_is_accepted_and_noise_sessions_need_no_topic():
    known = [summary("a"), summary("b"), summary("c"), summary("n", noise=True)]

    result = topic_map_from(request(), known)

    assert [t.name for t in result.topics] == ["Auth and MFA", "Other"]
    assert result.correction_groups[0].refs == (("a", 3),)


def test_a_missing_session_and_a_doubled_session_are_named():
    known = [summary("a"), summary("b"), summary("c"), summary("d")]
    doubled = request(
        topics=[
            {"name": "Topic one", "description": "x", "session_ids": ["a", "b", "c"]},
            {"name": "Topic two", "description": "x", "session_ids": ["c"]},
        ]
    )

    with pytest.raises(TopicMapError, match="missing: d") as missing:
        topic_map_from(doubled, known)
    assert "twice: c" in str(missing.value)


def test_an_unknown_id_and_a_long_name_are_refused():
    known = [summary("a"), summary("b"), summary("c")]
    with pytest.raises(TopicMapError, match="unknown session.*zzz"):
        topic_map_from(
            request(
                frictions=[{"name": "Friction name", "description": "d", "session_ids": ["zzz"]}]
            ),
            known,
        )
    long = {"name": "One two three four five", "description": "d", "session_ids": ["a", "b", "c"]}
    with pytest.raises(TopicMapError, match="name"):
        topic_map_from(request(topics=[long]), known)


def test_summaries_are_validated_field_by_field():
    good = {
        "session_id": "a",
        "goal": "Fix refunds",
        "outcome": "done",
        "friction": "",
        "noise": False,
    }
    assert summary_from(good).outcome == "done"
    with pytest.raises(SummaryError, match="goal"):
        summary_from(good | {"goal": " ".join(["word"] * 30)})
    with pytest.raises(SummaryError, match="outcome"):
        summary_from(good | {"outcome": "great"})
    with pytest.raises(SummaryError, match="noise"):
        summary_from(good | {"noise": "no"})
    with pytest.raises(SummaryError, match="friction"):
        summary_from(good | {"friction": " ".join(["w"] * 11)})
