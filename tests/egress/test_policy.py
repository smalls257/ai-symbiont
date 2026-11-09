"""The published egress policy reaches local servers only, decided with no network (Buffer)."""

import pytest

from symbiont.egress import Destination, EgressRefusedError, Endpoint, check_outbound

PUBLIC_URLS = [
    "https://api.meta.ai/v1/chat/completions",
    "https://api.anthropic.com/v1/messages",
    "https://example.com/collect",
    "https://" + "8.8." + "8.8/v1",
]


@pytest.mark.parametrize("endpoint", list(Endpoint))
@pytest.mark.parametrize("url", PUBLIC_URLS)
def test_no_endpoint_in_the_published_package_reaches_a_public_host(endpoint, url):
    with pytest.raises(EgressRefusedError):
        check_outbound(Destination(endpoint, url))


@pytest.mark.parametrize("endpoint", list(Endpoint))
def test_every_endpoint_refuses_a_url_without_http_or_a_host(endpoint):
    for url in ("ftp://127.0.0.1/x", "http:///nohost", "127.0.0.1:7377"):
        with pytest.raises(EgressRefusedError):
            check_outbound(Destination(endpoint, url))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8081/v1",
        "http://localhost:8081/v1",
        "http://glimmerbox:8081/v1",
        "http://lab" + ".lan/v1",
        "http://" + "192.168." + "0.9:8081/v1",
    ],
)
def test_local_glimmer_reaches_loopback_or_lan(url):
    check_outbound(Destination(Endpoint.LOCAL_GLIMMER, url))


@pytest.mark.parametrize("host", ["box.lan.", "printer.localdomain", "router.fritz.box"])
def test_lan_host_spellings_are_accepted_for_glimmer(host):
    check_outbound(Destination(Endpoint.LOCAL_GLIMMER, f"http://{host}/v1"))


def test_local_service_is_loopback_only():
    check_outbound(Destination(Endpoint.LOCAL_SERVICE, "http://127.0.0.1:7777/recall"))
    with pytest.raises(EgressRefusedError, match="loopback only"):
        check_outbound(
            Destination(Endpoint.LOCAL_SERVICE, "http://" + "192.168." + "0.9:7777/recall")
        )


@pytest.mark.parametrize("url", ["http://" + "192.168." + "0.9:8090/v1", "https://api.meta.ai"])
def test_the_memory_model_is_loopback_only(url):
    memory = Endpoint.LOCAL_MEMORY_MODEL
    check_outbound(Destination(memory, "http://127.0.0.1:8090/v1/chat/completions"))
    with pytest.raises(EgressRefusedError, match="loopback only"):
        check_outbound(Destination(memory, url))
