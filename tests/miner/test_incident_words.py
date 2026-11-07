"""Words for incident cards: empty corrections, noise reasons, trigger phrases."""

import pytest

from symbiont.miner.incident_words import is_empty_correction
from symbiont.miner.incidents import NoiseReason, noise_words


@pytest.mark.parametrize(
    "text",
    ["ok", "yes please", "/compact", "<command-name>/clear</command-name>", "ok, go ahead", ""],
)
def test_acknowledgments_and_slash_commands_are_empty_corrections(text):
    assert is_empty_correction(text)


@pytest.mark.parametrize(
    "text", ["no, don't mock the database, use the fixture", "ok but use the real db instead"]
)
def test_a_real_instruction_is_not_empty(text):
    assert not is_empty_correction(text)


def test_every_noise_reason_has_words_without_jargon():
    for reason in NoiseReason:
        assert noise_words(reason).strip()
    assert (
        noise_words(NoiseReason.THROWAWAY_SCRIPT)
        == "the agent's own throwaway script: its name repeats, its problem does not"
    )
