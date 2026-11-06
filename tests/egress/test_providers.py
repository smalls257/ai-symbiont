"""The provider table is the one place a remote host is added."""

import pytest

from symbiont.egress.policy import REMOTE_HOSTS
from symbiont.egress.remote_chat import PROVIDERS, UnknownProviderError, provider


def test_remote_hosts_are_exactly_the_providers_hosts():
    assert frozenset(p.host for p in PROVIDERS.values()) == REMOTE_HOSTS
    assert "api.meta.ai" in REMOTE_HOSTS


def test_every_provider_chat_url_is_https_on_its_own_host():
    for entry in PROVIDERS.values():
        assert entry.chat_url.startswith(f"https://{entry.host}/")


def test_an_unknown_provider_is_refused_naming_the_known_ones():
    with pytest.raises(UnknownProviderError, match="meta"):
        provider("nonesuch")
