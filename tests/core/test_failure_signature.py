"""Two failures are the same when the test and the message match, not when the exception class does.

Failure guarded against: a note about one assertion firing on every other assertion in the run.
"""

from symbiont.core.failure_signature import failure_detail, failure_signature, same_failure

ASSERT_A = (
    "FAILED tests/test_parser.py::test_total - assert 3 == 4\n"
    "_____ test_total _____\n>   assert total(x) == 4\nE   assert 3 == 4\n"
)
ASSERT_B = "FAILED tests/test_cli.py::test_help - assert 'a' == 'b'\nE   assert 'a' == 'b'\n"


def test_two_different_assertions_in_one_command_do_not_match():
    assert not same_failure(ASSERT_A, ASSERT_B)


def test_the_same_assertion_with_other_numbers_and_paths_matches():
    again = ASSERT_A.replace("3 == 4", "7 == 9").replace("tests/", "/tmp/run42/tests/")

    assert same_failure(again, ASSERT_A)


def test_the_same_message_in_a_different_test_does_not_match():
    other = ASSERT_A.replace("test_total", "test_other")

    assert not same_failure(other, ASSERT_A)


def test_hashes_and_addresses_are_normalized():
    first = "ValueError: bad object at 0x7f3a9c1b2d40 for build deadbeef1234"
    second = "ValueError: bad object at 0x7f00aa11bb22 for build cafebabe9999"

    assert same_failure(first, second)


def test_an_exception_line_is_enough_when_there_is_no_assertion_line():
    first = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"
    second = "ImportError: cannot import name 'tokenize'"

    assert same_failure(first, first)
    assert not same_failure(first, second)


def test_output_with_no_message_never_matches_even_itself():
    assert failure_signature("exit status 1") is None
    assert not same_failure("exit status 1", "exit status 1")


def test_the_detail_is_the_printed_message_trimmed():
    assert failure_detail(ASSERT_A) == "assert 3 == 4"
    assert failure_detail("E   " + "x" * 200).endswith("...")
    assert failure_detail("nothing here") == ""
