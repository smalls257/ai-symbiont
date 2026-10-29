import pytest

from symbiont.miner.secrets import REDACTED, scrub

# Assembled at run time so no credential-shaped literal is committed.
SAMPLES = [
    "gh" + "p_" + "x" * 36,
    "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "h" + "f_" + "y" * 34,
    "s" + "k-" + "z" * 32,
    "xo" + "xb-" + "1234567890-abcdef",
]


@pytest.mark.parametrize("secret", SAMPLES)
def test_provider_tokens_are_scrubbed(secret):
    assert scrub(f"export X={secret} && make") == f"export X={REDACTED} && make"


def test_credentials_by_name_bearer_and_url_passwords_are_scrubbed():
    text = "api_key=" + "q" * 20 + " Authorization: Bearer " + "w" * 24
    text += " https://bob:" + "hunter2hunter2" + "@host.example/x"
    cleaned = scrub(text)
    assert "q" * 20 not in cleaned and "w" * 24 not in cleaned and "hunter2" not in cleaned


def test_ordinary_text_is_untouched():
    text = "pytest tests/test_tokens.py failed with ImportError; token count 12"
    assert scrub(text) == text
