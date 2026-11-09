from symbiont.records.session_tags import (
    CREATED_TAG,
    REFUSED_TAG,
    branch_tag,
    tag_values,
    title_tag,
)


def test_created_is_the_plain_word_the_miner_will_look_for():
    assert CREATED_TAG == "created"


def test_tag_values_read_back_what_the_builders_wrote():
    tags = (title_tag("Fix parser"), branch_tag("main"), CREATED_TAG)
    assert tag_values(tags, "ai-title:") == ("Fix parser",)
    assert tag_values(tags, "branch:") == ("main",)


def test_refused_is_the_plain_word_the_miner_will_look_for():
    assert REFUSED_TAG == "refused"
