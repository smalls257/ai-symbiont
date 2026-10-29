"""A redirect never carries the bearer key to another host: post_json refuses to follow one."""

import http.server
import threading
import urllib.error

import pytest

from symbiont.egress import Destination, Endpoint, post_json
from symbiont.egress.credentials import ApiKey

SECRET = "test-token-value"


class Recorder(http.server.BaseHTTPRequestHandler):
    seen: list[str | None] = []

    def _answer(self):
        Recorder.seen.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    # urllib turns a 301/302/303 POST into a GET and keeps the headers, so answer both
    def do_POST(self):  # noqa: N802
        self._answer()

    def do_GET(self):  # noqa: N802
        self._answer()

    def log_message(self, *args):
        return


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.periphery
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_an_error_and_the_key_never_reaches_the_target(status):
    Recorder.seen = []
    target = serve(Recorder)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(status)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/steal")
            self.end_headers()

        def log_message(self, *args):
            return

    origin = serve(Redirector)
    destination = Destination(
        Endpoint.LOCAL_GLIMMER, f"http://127.0.0.1:{origin.server_port}/v1", ApiKey(SECRET)
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        post_json(destination, {"p": 1})
    assert caught.value.code == status
    assert Recorder.seen == []
    origin.shutdown()
    target.shutdown()
