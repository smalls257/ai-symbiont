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


def test_the_user_name_of_a_home_directory_is_scrubbed_in_every_spelling():
    from symbiont.miner.credential_patterns import scrub as scrub_text

    for text, kept in (
        ("cat /Users/you/Code/app/notes.md", "cat ~/Code/app/notes.md"),
        ("ls /home/somebody", "ls ~"),
        (
            "/tmp/claude-1000/-home-somebody-Projects-app/abc/tasks/b1.output",
            "/tmp/claude-1000/-~-Projects-app/abc/tasks/b1.output",
        ),
        ("~/.claude/projects/-Users-somebody-Code-app/x.md", "~/.claude/projects/-~-Code-app/x.md"),
    ):
        assert scrub_text(text) == kept
    assert scrub_text("see /usr/home/share and src/home/page.tsx") == (
        "see /usr/home/share and src/home/page.tsx"
    )
