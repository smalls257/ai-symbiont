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
    "you should never push straight to main",
    "use pnpm, not npm",
    "ok please stop the dev server, you started it twice",
    "never commit scratch files",
    "that broke the build",
    "stop doing that",
    "instead of guessing, read the error first",
    "ok the tests are still failing",
    "ok, don't push yet",
    "the post is too long. don't use jargon",
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
    # A request that carries a reminder is still a request: reminders are not refusals.
    "please update the docs with the container details. make sure to list the ports",
    "yeah lets remove the old stores. dont forget about the branch being merged",
    "yes please implement this change, don't forget to run the tests",
    "please remember to revert when we are done",
    "the checkbox should always be displayed, not only when selection is active",
    "ok i think its safe to stop the api now",
    "you can stop the various review scripts",
    "always run the linter before you commit",
    # A contrast or a "don't" that describes, and a status report, are not refusals.
    "i want to discuss the scope, we could ship auth instead of search first",
    "ok the node is on local docker, not the remote host",
    "ok this is interesting, i saw it before but dont remember the details",
    "ok so finishing phase 6 needs a staging wipe and the deploy job is failing",
    # A limit that rides on a request opens no sentence; a negative question asks.
    "commit the changes, don't push yet",
    "go ahead, but do not add the beta tool to the list",
    "issue 625 points at the old repo as a pr, instead of the new one",
    "dont we need to revert the migration too?",
    "Don't you see any security issue with these tools?",
    # A pasted document's ground rules are not the developer pushing back.
    "# Agent Instructions\n\nYou run headless.\n\n## Ground rules\n\n1. Never use plan mode.",
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
