"""A dataset "correction" label counts only when the message pushes back."""

import pytest

from symbiont.miner.pushback import pushes_back

PUSHBACK = [
    "no, don't push this to main",
    "noooo why did you tag the release yourself?",
    "dont use that key, you have an ssh key via the cli",
    "wait a second, the release flow got short-circuited",
    "stop the review, the bot hasnt posted yet",
    "please revert the tag",
    "you forgot to update the docs",
    "that's not what I asked",
    "I said use the staging branch",
    "it's still failing on CI",
    "the checkbox should always be displayed",
    "never commit scratch files",
    "that broke the build",
    "stop doing that",
]
REQUESTS = [
    "please push and open a pr",
    "ok credit card added and $20 allocated",
    "can you also add more examples",
    "how much work remains in the todo",
    "ok lets split 1021 into a separate pr",
    "yeah lets do it",
    "No problem, go ahead",
    "no worries",
    "no thanks, looks great",
    "wait for the build then push",
    "never mind",
    "Don't worry about it",
    "please stop by the docs later",
    "I'm AFK, just commit",
]


@pytest.mark.parametrize("text", PUSHBACK)
def test_pushback_wording_is_a_correction(text):
    assert pushes_back(text)


@pytest.mark.parametrize("text", REQUESTS)
def test_a_plain_request_is_not_a_correction(text):
    assert not pushes_back(text)


def test_only_the_first_300_characters_count():
    assert not pushes_back("please push the branch\n" + "x " * 150 + "you forgot the docs")


# "No," answering the agent's question and then agreeing is assent, not pushback (review I6).
ASSENT_AFTER_OPENER = [
    "no, that all checks out, could you do the next one",
    "No, that's fine. go ahead and merge",
    "no that's fine",
    "no, go ahead",
    "no, not yet",
    "no, looks good",
    "no worries",
    "no, all good",
    "No, I haven't run it yet",
    "wait, that's fine actually",
]
OPENER_THEN_REFUSAL = [
    "no, use pnpm",
    "no, don't push to main",
    "noooo why did you delete the branch",
    "no, that's wrong",
    "wait, why did you skip the tests",
]


@pytest.mark.parametrize("text", ASSENT_AFTER_OPENER)
def test_an_opener_followed_by_assent_is_not_pushback(text):
    assert not pushes_back(text)


@pytest.mark.parametrize("text", OPENER_THEN_REFUSAL)
def test_an_opener_followed_by_a_refusal_is_pushback(text):
    assert pushes_back(text)
