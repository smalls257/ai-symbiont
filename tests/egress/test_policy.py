"""The egress policy refuses what must not leave and allows what may, with no network (Buffer)."""

import pytest

from symbiont.egress import Destination, EgressRefusedError, Endpoint, check_outbound
from symbiont.records.schema import Provenance

SAFE = Provenance(dataset="openhands", licence="MIT", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", licence="private", spark_safe=False)
SWE_CHAT = Provenance(dataset="SWE-chat", licence="research", spark_safe=True)
REMOTE_URL = "https://api.meta.ai/v1/chat/completions"


@pytest.mark.parametrize("endpoint", [Endpoint.SPARK, Endpoint.CONTRIBUTOR, Endpoint.WONDER])
def test_remote_endpoints_take_spark_safe_records(endpoint):
    check_outbound(Destination(endpoint, REMOTE_URL), [SAFE, SAFE])


@pytest.mark.parametrize("endpoint", [Endpoint.SPARK, Endpoint.CONTRIBUTOR, Endpoint.WONDER])
@pytest.mark.parametrize("bad", [[PRIVATE], [SAFE, PRIVATE], [SWE_CHAT], []])
def test_remote_endpoints_refuse_private_or_undeclared_provenance(endpoint, bad):
    with pytest.raises(EgressRefusedError):
        check_outbound(Destination(endpoint, REMOTE_URL), bad)


def test_the_refusal_names_the_dataset_not_any_text():
    with pytest.raises(EgressRefusedError, match="owner-sessions"):
        check_outbound(Destination(Endpoint.SPARK, REMOTE_URL), [PRIVATE])


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://" + "10." + "0.0.5/v1",
        "https://box" + ".local/v1",
        "ftp://x.com",
    ],
)
def test_remote_endpoints_refuse_plain_http_private_hosts_and_other_schemes(url):
    with pytest.raises(EgressRefusedError):
        check_outbound(Destination(Endpoint.SPARK, url), [SAFE])


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
def test_local_glimmer_takes_private_provenance_on_loopback_or_lan(url):
    check_outbound(Destination(Endpoint.LOCAL_GLIMMER, url), [PRIVATE])
    check_outbound(Destination(Endpoint.LOCAL_GLIMMER, url))


def test_local_glimmer_refuses_a_public_host():
    with pytest.raises(EgressRefusedError):
        check_outbound(Destination(Endpoint.LOCAL_GLIMMER, "https://api.meta.ai/v1"), [])


def test_local_service_is_loopback_only():
    check_outbound(Destination(Endpoint.LOCAL_SERVICE, "http://127.0.0.1:7777/recall"))
    with pytest.raises(EgressRefusedError):
        check_outbound(
            Destination(Endpoint.LOCAL_SERVICE, "http://" + "192.168." + "0.9:7777/recall")
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "https://api.meta.ai.evil.example/v1",
        "https://evil.example/api.meta.ai",
        "https://api.meta.ai:8443" + "@evil.example/v1",
    ],
)
def test_remote_endpoints_refuse_any_host_but_the_listed_one(url):
    with pytest.raises(EgressRefusedError, match="not an allowed remote host"):
        check_outbound(Destination(Endpoint.SPARK, url), [SAFE])


def test_the_listed_host_passes_with_a_trailing_dot_and_any_case():
    check_outbound(Destination(Endpoint.SPARK, "https://API.Meta.AI./v1"), [SAFE])


@pytest.mark.parametrize("host", ["box.lan.", "printer.localdomain", "router.fritz.box"])
def test_private_host_spellings_are_refused_for_remote_and_accepted_for_glimmer(host):
    with pytest.raises(EgressRefusedError):
        check_outbound(Destination(Endpoint.SPARK, f"https://{host}/v1"), [SAFE])
    check_outbound(Destination(Endpoint.LOCAL_GLIMMER, f"http://{host}/v1"))
