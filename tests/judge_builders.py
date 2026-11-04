"""Builders shared by the agree-rule recall tests: lessons, a fake judge, a service over them."""

import json

from symbiont.core.counters import Counters
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.service.app import Service, ServiceMode, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.judge_model import JudgeModel
from symbiont.store.local import Source, Store

PROJECT = "demo"
URL = "http://127.0.0.1:8791"
QUESTION = "tool7 module7 failed with Oops7 again, what now?"


def lesson(index, fix):
    signature = Signature(Signal.FAILED_COMMAND, (f"tool{index}", f"module{index}", f"Oops{index}"))
    pain = PainPoint(signature, f"s{index}", 1, ((f"s{index}", 1),))
    return Lesson(
        pain, f"$ tool{index} module{index}\nOops{index}", (fix,), None, True, pain.record_refs
    )


def judge_saying(p_yes):
    def transport(request, timeout_s):
        return json.dumps({"p_yes": [p_yes]}).encode()

    return JudgeModel(URL, transport)


def service_with(tmp_path, judge):
    store = Store.open(tmp_path / "store.db")
    lessons = [lesson(index, "ran `a`") for index in range(40)] + [lesson(7, "ran `b`")]
    store.save_mining(
        PROJECT, [Source(PROJECT, "claude_code", "x")], lessons, held_out_tasks=frozenset()
    )
    parts = ServiceParts(
        store, Counters(), EventLog(tmp_path / "run", "c"), ServiceMode.RECALL_ONLY, judge=judge
    )
    return Service(parts)


def recall(service):
    return service.respond("/recall", {"question": QUESTION, "project": PROJECT})


def saying_transport(p_yes, seen=None):
    """A judge transport that answers every score with `p_yes` and records each request body."""

    def transport(request, timeout_s):
        if seen is not None:
            seen.append(json.loads(request.data))
        return json.dumps({"p_yes": [p_yes]}).encode()

    return transport
