"""The API key is loaded in code, never repr'd, never logged, and a missing one raises."""

import json
import logging
import urllib.request

import pytest

from symbiont.egress import Destination, Endpoint, post_json
from symbiont.egress.credentials import ApiKey, MissingCredentialError, load_meta_key
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)
URL = "https://api.meta.ai/v1/chat/completions"
SECRET = "test-token-value"


def test_the_key_is_read_from_the_env_file_and_hidden_from_repr(tmp_path):
    path = tmp_path / "meta.env"
    path.write_text(f"# comment\nOTHER=1\nMETA_API_KEY={SECRET}\n")
    key = load_meta_key(path)
    assert key.reveal() == SECRET
    assert SECRET not in repr(key) and SECRET not in str(
        Destination(Endpoint.CONTRIBUTOR, URL, key)
    )


def test_a_missing_file_or_variable_raises_naming_the_variable_not_the_value(tmp_path):
    with pytest.raises(MissingCredentialError, match="META_API_KEY"):
        load_meta_key(tmp_path / "absent.env")
    empty = tmp_path / "meta.env"
    empty.write_text("OTHER=1\n")
    with pytest.raises(MissingCredentialError, match="META_API_KEY"):
        load_meta_key(empty)


def test_post_json_sends_the_bearer_header_and_never_logs_it(caplog):
    caplog.set_level(logging.DEBUG, logger="symbiont.egress")
    seen = []

    def transport(request: urllib.request.Request, timeout_s: float) -> bytes:
        seen.append(request.get_header("Authorization"))
        return json.dumps({}).encode()

    destination = Destination(Endpoint.CONTRIBUTOR, URL, ApiKey(SECRET))
    post_json(destination, {"p": 1}, provenance=[SAFE], transport=transport)
    assert seen == [f"Bearer {SECRET}"]
    assert SECRET not in caplog.text


def test_no_key_means_no_authorization_header():
    seen = []

    def transport(request, timeout_s):
        seen.append(request.get_header("Authorization"))
        return b"{}"

    post_json(
        Destination(Endpoint.LOCAL_GLIMMER, "http://127.0.0.1:8081/v1"), {}, transport=transport
    )
    assert seen == [None]
