from symbiont.records.ours import OUR_OUTPUT_TAG, is_our_output, split_our_output


def test_tag_line_is_detected():
    assert is_our_output(f"ok\n{OUR_OUTPUT_TAG}\nYou reworked this file twice.")
    assert is_our_output(OUR_OUTPUT_TAG)


def test_tag_must_be_a_whole_line():
    assert not is_our_output("see [symbiont] docs")
    assert not is_our_output(f"{OUR_OUTPUT_TAG} extra")
    assert not is_our_output("")


def test_split_keeps_the_harness_text_before_the_tag():
    own, ours = split_our_output(f"3 passed\n{OUR_OUTPUT_TAG}\nnote\n")
    assert own == "3 passed\n"
    assert ours == f"{OUR_OUTPUT_TAG}\nnote\n"


def test_split_without_tag_returns_text_untouched():
    assert split_our_output("plain") == ("plain", "")
