"""The card reaches the player as prose before the game prompt; the empty card changes nothing."""

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.card_prompt import LESSONS_HEADING, RULES_HEADING, system_rules, with_card
from symbiont.act1.episode import build_prompt
from symbiont.act1.glimmer import Reply

GAME_PROMPT = build_prompt("You are in a room.", ["scripted turn(90) -> timeout after 60 tics"])


def recorder():
    seen = []

    def reply_fn(prompt):
        seen.append(prompt)
        return Reply("turn(90)", "stop", 0)

    return reply_fn, seen


def card():
    return Card.of(
        [
            Lesson("Turned in a checked room", "Walk to the next door", "Is anything new in view?"),
            Lesson("Fired at nothing", "Shoot only at a visible enemy", "Is an enemy in view?"),
        ]
    )


def test_the_empty_card_returns_the_same_function_so_the_prompt_is_byte_identical():
    reply_fn, seen = recorder()
    assert with_card(reply_fn, Card.of([])) is reply_fn
    with_card(reply_fn, Card.of([]))(GAME_PROMPT)
    assert seen == [GAME_PROMPT]


def test_a_cards_text_comes_before_the_game_prompt():
    reply_fn, seen = recorder()
    with_card(reply_fn, card())(GAME_PROMPT)
    (prompt,) = seen
    assert prompt == f"{LESSONS_HEADING}\n{card().render()}\n\n{GAME_PROMPT}"
    assert prompt.index("Walk to the next door") < prompt.index("You play a Freedoom level")


def test_every_call_gets_the_lessons_and_the_reply_comes_back_unchanged():
    reply_fn, seen = recorder()
    wrapped = with_card(reply_fn, card())
    replies = [wrapped(GAME_PROMPT), wrapped("second prompt")]
    assert all(r == Reply("turn(90)", "stop", 0) for r in replies)
    assert all(p.startswith(LESSONS_HEADING) for p in seen) and len(seen) == 2


def test_the_prompt_holds_no_score_or_card_id():
    reply_fn, seen = recorder()
    with_card(reply_fn, card())(GAME_PROMPT)
    assert card().card_id not in seen[0]


def test_the_system_rules_hold_the_card_under_a_must_follow_heading_and_the_empty_card_none():
    assert system_rules(card()) == f"{RULES_HEADING}\n{card().render()}"
    assert system_rules(Card.of([])) is None
