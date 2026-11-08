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
