"""Putting a new night's adapter live in a running judge server.

Violation prevented: Silent Fallback. A server that does not confirm the exact adapter raises, so
a night never reports a fresh adapter live while the judge still answers from yesterday's.
"""

import json
from pathlib import Path

import pytest

from symbiont.service.judge_model import JudgeModel, JudgeOfflineError

URL = "http://127.0.0.1:8861"
ADAPTER = Path("/data/nightly/demo/adapter")


def transport_replying(reply):
    seen = []

    def transport(request, timeout_s):
        seen.append((request.full_url, json.loads(request.data)))
        return json.dumps(reply).encode()

    transport.seen = seen
    return transport


def test_reload_posts_the_adapter_folder_to_the_servers_reload_route():
    transport = transport_replying({"loaded": str(ADAPTER)})
    JudgeModel(URL, transport).reload(ADAPTER)
    assert transport.seen == [(URL + "/reload", {"adapter": str(ADAPTER)})]


def test_a_reply_that_names_another_adapter_raises():
    with pytest.raises(JudgeOfflineError, match="did not confirm"):
        JudgeModel(URL, transport_replying({"loaded": "/old"})).reload(ADAPTER)


def test_a_server_that_refuses_or_is_down_raises_offline():
    def refusing(request, timeout_s):
        raise ConnectionRefusedError

    with pytest.raises(JudgeOfflineError, match="would not reload"):
        JudgeModel(URL, refusing).reload(ADAPTER)
