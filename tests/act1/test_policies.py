import pytest

from symbiont.act1.policies import (
    EXPLORER_CYCLE,
    policy_named,
    random_policy,
    scripted_explorer,
)
from symbiont.act1.strategy import parse_strategy


def _replies(policy, count):
    return [policy.reply("ignored prompt").text for _ in range(count)]


def test_random_policy_is_reproducible_from_its_seed():
    first = _replies(random_policy(3), 20)
    assert first == _replies(random_policy(3), 20)
    assert first != _replies(random_policy(4), 20)


def test_every_policy_reply_parses_as_a_strategy():
    for policy in (random_policy(1), scripted_explorer(1)):
        for reply in (policy.reply("p") for _ in range(50)):
            assert parse_strategy(reply.text)
            assert reply.finish_reason == "stop"
            assert reply.reasoning_chars == 0


def test_explorer_seeds_differ_in_their_opening_turn():
    openings = {_replies(scripted_explorer(seed), 1)[0] for seed in range(1, 8)}
    assert len(openings) >= 2
    assert all(opening.startswith("turn(") for opening in openings)


def test_explorer_cycles_through_its_moves_after_the_opening():
    replies = _replies(scripted_explorer(5), 1 + 2 * len(EXPLORER_CYCLE))
    assert replies[1:] == list(EXPLORER_CYCLE) * 2


def test_policy_names_are_stable_for_session_ids():
    assert random_policy(0).name == "random"
    assert scripted_explorer(0).name == "scripted_explorer"
    assert policy_named("random", 2).name == "random"


def test_policy_named_refuses_an_unknown_name():
    with pytest.raises(ValueError, match="random.*scripted_explorer"):
        policy_named("wander", 1)


GAMING_POLICIES = {
    "stand_still": "turn(0)",
    "fire_in_place": "\n".join(["shoot_nearest()"] * 3),
    "spin": "\n".join(["turn(90)"] * 3),
}


@pytest.mark.parametrize(("name", "reply"), sorted(GAMING_POLICIES.items()))
def test_each_gaming_policy_says_the_same_valid_thing_every_time(name, reply):
    policy = policy_named(name, 1)
    assert policy.name == name
    assert _replies(policy, 5) == [reply] * 5
    assert parse_strategy(reply)


def test_gaming_policies_take_a_seed_like_the_others_and_unknown_names_still_raise():
    assert policy_named("spin", 99).name == "spin"
    with pytest.raises(ValueError, match="unknown policy"):
        policy_named("dance", 1)
