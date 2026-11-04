"""The GET-only model door: https and Hugging Face hosts only, redirects included, atomic files.

No test here touches a network: the opener is a fake.
"""

import io
import urllib.request

import pytest

from symbiont.egress import DownloadError, EgressRefusedError, download_file, get_json
from symbiont.egress.download import _AllowlistedRedirects, check_download_url

HF_FILE = "https://huggingface.co/unsloth/Llama-3.2-1B-Instruct/resolve/main/config.json"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def serving(payload: bytes, seen: list[urllib.request.Request] | None = None):
    def opener(request, timeout_s):
        if seen is not None:
            seen.append(request)
        return FakeResponse(payload)

    return opener


@pytest.mark.parametrize(
    "url",
    [
        HF_FILE,
        "https://cas-bridge.xethub.hf.co/xet-bridge-us/abc",
        "https://cdn-lfs.hf.co/repos/x",
        "https://us.aws.cdn.hf.co/xet-bridge-us/abc?sig=1",
    ],
)
def test_huggingface_and_its_cdn_hosts_are_allowed(url):
    check_download_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://huggingface.co/x",
        "https://evil.example.com/x",
        "https://huggingface.co.evil.com/x",
        "https://evilhf.co/x",
        "https://hf.co.evil.com/x",
        "file:///etc/passwd",
        "https://127.0.0.1/x",
    ],
)
def test_other_hosts_and_schemes_are_refused(url):
    with pytest.raises(EgressRefusedError):
        check_download_url(url)


def test_a_refused_url_never_reaches_the_opener(tmp_path):
    seen: list = []
    with pytest.raises(EgressRefusedError):
        download_file("https://evil.example.com/m", tmp_path / "m", 1, opener=serving(b"x", seen))
    assert seen == [] and list(tmp_path.iterdir()) == []


def test_a_redirect_to_a_non_allowlisted_host_is_refused():
    handler = _AllowlistedRedirects()
    request = urllib.request.Request(HF_FILE)
    with pytest.raises(EgressRefusedError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example.com/x")


def test_a_redirect_to_http_is_refused():
    handler = _AllowlistedRedirects()
    with pytest.raises(EgressRefusedError):
        handler.redirect_request(
            urllib.request.Request(HF_FILE), None, 302, "Found", {}, "http://cdn-lfs.hf.co/x"
        )


def test_a_redirect_to_the_cdn_is_followed_as_a_plain_get_without_a_body():
    followed = _AllowlistedRedirects().redirect_request(
        urllib.request.Request(HF_FILE), None, 302, "Found", {}, "https://us.aws.cdn.hf.co/a?b=1"
    )
    assert followed is not None and followed.get_method() == "GET" and followed.data is None


def test_the_request_is_a_get_with_no_body_and_no_credential(tmp_path):
    seen: list = []
    download_file(HF_FILE, tmp_path / "config.json", 3, opener=serving(b"abc", seen))
    request = seen[0]
    assert request.get_method() == "GET" and request.data is None
    assert not any(name.lower() == "authorization" for name in request.headers)


def test_the_file_appears_whole_and_no_part_file_stays(tmp_path):
    target = tmp_path / "deep" / "config.json"
    reports: list = []
    written = download_file(
        HF_FILE, target, 3, lambda done, total: reports.append((done, total)), serving(b"abc")
    )
    assert written == 3 and target.read_bytes() == b"abc"
    assert [path.name for path in target.parent.iterdir()] == ["config.json"]
    assert reports[-1] == (3, 3)


def test_a_short_file_raises_and_leaves_nothing_under_the_final_name(tmp_path):
    target = tmp_path / "model.safetensors"
    with pytest.raises(DownloadError, match=r"huggingface\.co/.*gave 2 bytes, expected 3"):
        download_file(HF_FILE, target, 3, opener=serving(b"ab"))
    assert list(tmp_path.iterdir()) == []


def test_a_failed_download_does_not_replace_an_existing_good_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_bytes(b"old")
    with pytest.raises(DownloadError):
        download_file(HF_FILE, target, 9, opener=serving(b"short"))
    assert target.read_bytes() == b"old"


def test_a_network_error_becomes_a_download_error_naming_host_and_path_not_the_query(tmp_path):
    def broken(request, timeout_s):
        raise OSError("connection reset")

    url = HF_FILE + "?Signature=SECRET"
    with pytest.raises(DownloadError) as raised:
        download_file(url, tmp_path / "x", 1, opener=broken)
    assert "huggingface.co/unsloth" in str(raised.value) and "SECRET" not in str(raised.value)


def test_get_json_decodes_and_rejects_non_json():
    assert get_json(HF_FILE, serving(b'[{"path": "a"}]')) == [{"path": "a"}]
    with pytest.raises(DownloadError, match="did not answer JSON"):
        get_json(HF_FILE, serving(b"<html>"))
