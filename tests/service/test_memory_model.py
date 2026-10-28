import json

import pytest

from symbiont.core.memory_note import SYSTEM
from symbiont.egress import EgressRefusedError
from symbiont.service.memory_model import MemoryModel, MemoryModelOfflineError

pytestmark = pytest.mark.periphery

LINE = (
    "Happened: `pytest` failed with ImportError -> Resolved: you ran `pip install x`"
    " -> Check: run `pytest`"
)


def replying(content, seen=None):
    def transport(request, timeout_s):
        if seen is not None:
            seen.append((request.full_url, json.loads(request.data)))
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    return transport


def test_a_valid_line_comes_back_with_its_cost_and_the_request_is_greedy_one_line():
    seen = []
    memory = MemoryModel("http://127.0.0.1:8090", frozenset({"demo"}), replying(LINE, seen))
    reply = memory.write_line("In demo, `pytest` failed.")
    assert reply.line == LINE and reply.prompt_chars == len("In demo, `pytest` failed.")
    assert reply.elapsed_ms >= 0
    url, body = seen[0]
    assert url == "http://127.0.0.1:8090/v1/chat/completions"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    assert (body["temperature"], body["stop"], body["model"]) == (0.0, ["\n"], "default_model")


@pytest.mark.parametrize("content", ["", "just some prose", None])
def test_an_unusable_reply_is_offline_never_a_blank_note(content):
    memory = MemoryModel("http://127.0.0.1:8090", frozenset(), replying(content))
    with pytest.raises(MemoryModelOfflineError, match="unusable"):
        memory.write_line("prompt")


def test_a_reply_without_choices_is_offline():
    memory = MemoryModel("http://127.0.0.1:8090", frozenset(), lambda request, timeout: b"{}")
    with pytest.raises(MemoryModelOfflineError, match="choices"):
        memory.write_line("prompt")


def test_an_unreachable_server_is_offline():
    def refused(request, timeout_s):
        raise ConnectionRefusedError("refused")

    memory = MemoryModel("http://127.0.0.1:8090", frozenset(), refused)
    with pytest.raises(MemoryModelOfflineError, match="ConnectionRefusedError"):
        memory.write_line("prompt")


def test_a_non_loopback_memory_model_is_refused_before_sending():
    memory = MemoryModel("http://" + "10.0." + "0.5:8090", frozenset(), replying(LINE))
    with pytest.raises(EgressRefusedError):
        memory.write_line("prompt")


def test_knows_only_the_trained_projects():
    memory = MemoryModel("http://127.0.0.1:8090", frozenset({"demo"}))
    assert memory.knows("demo") and not memory.knows("other")
