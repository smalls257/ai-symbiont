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


def _exchange(httpd, method, route, headers, body=None):
    """One request with exactly these headers (http.client adds Host only when we leave it out)."""
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    conn.putrequest(method, route, skip_host="Host" in headers)
    for name, value in headers.items():
        conn.putheader(name, value)
    payload = json.dumps(body).encode() if body is not None else b""
    if method == "POST":
        conn.putheader("Content-Length", str(len(payload)))
    conn.endheaders(payload)
    reply = conn.getresponse()
    answer = reply.status, reply.read()
    conn.close()
    return answer


def test_a_foreign_host_is_refused_with_403_and_a_reason(listening):
    status, body = _exchange(listening, "GET", "/dashboard", {"Host": "evil.example:7377"})

    assert status == 403 and b"Host" in body


def test_a_missing_host_is_refused(listening):
    conn = http.client.HTTPConnection("127.0.0.1", listening.server_address[1], timeout=5)
    conn.putrequest("GET", "/dashboard", skip_host=True)
    conn.endheaders()

    assert conn.getresponse().status == 403


def test_every_loopback_name_with_our_port_or_none_is_answered(listening):
    port = listening.server_address[1]
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", "localhost"):
        assert _exchange(listening, "GET", "/dashboard", {"Host": host})[0] != 403, host


def test_a_loopback_name_on_another_port_is_refused(listening):
    port = listening.server_address[1]

    assert _exchange(listening, "GET", "/dashboard", {"Host": f"127.0.0.1:{port + 1}"})[0] == 403


def test_a_post_from_a_foreign_origin_is_refused_but_no_origin_and_ours_are_answered(listening):
    port = listening.server_address[1]
    body = {"question": "q"}
    post = lambda origin: _exchange(  # noqa: E731
        listening, "POST", "/recall", {"Origin": origin} if origin else {}, body
    )

    assert post("http://evil.example")[0] == 403
    assert post("null")[0] == 403
    assert post(None)[0] == 400  # the route answered (a bad body), the guard did not refuse
    assert post(f"http://127.0.0.1:{port}")[0] == 400


def test_the_dashboard_answers_with_the_right_host(listening):
    assert _exchange(listening, "GET", "/dashboard?project=x", {})[0] == 200
