import http.client
import inspect
import json
import threading
import urllib.error
import urllib.request

import pytest

from symbiont.core.counters import Counters
from symbiont.egress import Destination, EgressRefusedError, Endpoint, post_json
from symbiont.service import server
from symbiont.service.app import Service, ServiceParts
from symbiont.service.events import EventLog
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
HOST_LIKE = {"host", "bind", "address", "interface", "hostname"}


@pytest.fixture
def listening(tmp_path):
    store = Store.open(tmp_path / "store.db")
    service = Service(ServiceParts(store, Counters(), EventLog(tmp_path / "run", "counters")))
    httpd = server.bind(service, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def url(httpd, route):
    return f"http://127.0.0.1:{httpd.server_address[1]}{route}"


def test_the_listener_binds_loopback_only(listening):
    assert listening.server_address[0] == "127.0.0.1"


def test_neither_entry_point_takes_a_host():
    for entry in (server.serve, server.bind):
        assert HOST_LIKE.isdisjoint(inspect.signature(entry).parameters), entry


def test_recall_over_http_through_the_egress_door(listening):
    body = {"question": "what failed?", "project": "tobymao/sqlglot"}
    reply = post_json(Destination(Endpoint.LOCAL_SERVICE, url(listening, "/recall")), body)
    assert reply == {"answer": "no history for this project yet", "records": []}


def test_a_refused_request_is_a_status_not_an_empty_answer(listening):
    request = urllib.request.Request(
        url(listening, "/recall"), data=json.dumps({"question": "q"}).encode(), method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310
    assert refused.value.code == 400 and b"missing fields" in refused.value.read()


def test_a_body_that_is_not_json_is_a_400(listening):
    request = urllib.request.Request(url(listening, "/observe"), data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310
    assert refused.value.code == 400


def test_the_egress_policy_refuses_a_non_loopback_service_host():
    with pytest.raises(EgressRefusedError):
        post_json(Destination(Endpoint.LOCAL_SERVICE, "http://" + "10.0." + "0.5:7377/recall"), {})


def test_a_malformed_content_length_is_a_400_not_a_dropped_connection(listening):
    connection = http.client.HTTPConnection("127.0.0.1", listening.server_address[1], timeout=5)
    connection.putrequest("POST", "/recall")
    connection.putheader("Content-Length", "abc")
    connection.endheaders()
    reply = connection.getresponse()
    assert reply.status == 400
    connection.close()
