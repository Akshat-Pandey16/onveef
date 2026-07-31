"""Tests for URL repair: the host rewriting that keeps NAT'd devices reachable."""

from __future__ import annotations

import pytest

from onveef import urls

DEVICE = "http://203.0.113.9:8000/onvif/device_service"


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("http://192.168.1.64/onvif/media", "http://203.0.113.9:8000/onvif/media"),
        ("http://192.168.1.64:80/onvif/ptz", "http://203.0.113.9:8000/onvif/ptz"),
        ("http://0.0.0.0/onvif/events", "http://203.0.113.9:8000/onvif/events"),
        ("https://192.168.1.64:443/onvif/media", "http://203.0.113.9:8000/onvif/media"),
    ],
)
def test_http_xaddrs_take_scheme_host_and_port(reported: str, expected: str) -> None:
    """SOAP endpoints live on the device's web server, so the whole authority is replaced."""
    assert urls.rewrite_host(reported, DEVICE) == expected


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("rtsp://192.168.1.64:554/Streaming/1", "rtsp://203.0.113.9:554/Streaming/1"),
        ("rtsp://0.0.0.0/live", "rtsp://203.0.113.9/live"),
        ("rtsps://10.1.2.3:322/live", "rtsps://203.0.113.9:322/live"),
    ],
)
def test_non_http_schemes_keep_their_own_port(reported: str, expected: str) -> None:
    """RTSP runs on its own daemon and port; only the host is wrong."""
    assert urls.rewrite_host(reported, DEVICE) == expected


def test_query_and_fragment_survive() -> None:
    rewritten = urls.rewrite_host("http://10.0.0.5/img?ch=1&q=high#top", DEVICE)
    assert rewritten == "http://203.0.113.9:8000/img?ch=1&q=high#top"


def test_existing_userinfo_is_preserved() -> None:
    rewritten = urls.rewrite_host("rtsp://bob:s3cret@10.0.0.5:554/live", DEVICE)
    assert rewritten == "rtsp://bob:s3cret@203.0.113.9:554/live"


def test_ipv6_reference_is_bracketed() -> None:
    rewritten = urls.rewrite_host("http://10.0.0.5/onvif/media", "http://[2001:db8::1]/dev")
    assert rewritten == "http://[2001:db8::1]/onvif/media"


@pytest.mark.parametrize("value", ["", "not a url", "/relative/path"])
def test_unparseable_urls_pass_through(value: str) -> None:
    assert urls.rewrite_host(value, DEVICE) == value


def test_empty_reference_is_a_no_op() -> None:
    assert urls.rewrite_host("http://10.0.0.5/x", "") == "http://10.0.0.5/x"


def test_already_correct_url_is_returned_identically() -> None:
    same = "http://203.0.113.9:8000/onvif/media"
    assert urls.rewrite_host(same, DEVICE) is same


def test_rewrite_service_map() -> None:
    mapped = urls.rewrite_service_map(
        {"media": "http://192.168.1.64/onvif/media", "ptz": ""}, DEVICE
    )
    assert mapped["media"] == "http://203.0.113.9:8000/onvif/media"
    assert mapped["ptz"] == ""


def test_with_credentials_percent_encodes_reserved_characters() -> None:
    """A password containing @ : / would corrupt a hand-built URL."""
    out = urls.with_credentials("rtsp://10.0.0.9:554/s1", "adm in", "p@ss:/w")
    assert out == "rtsp://adm%20in:p%40ss%3A%2Fw@10.0.0.9:554/s1"


def test_with_credentials_replaces_existing_userinfo() -> None:
    out = urls.with_credentials("rtsp://old:pw@10.0.0.9/s", "new", "np")
    assert out == "rtsp://new:np@10.0.0.9/s"


def test_with_credentials_without_password() -> None:
    assert urls.with_credentials("rtsp://10.0.0.9/s", "admin") == "rtsp://admin@10.0.0.9/s"


def test_with_credentials_no_username_is_a_no_op() -> None:
    assert urls.with_credentials("rtsp://10.0.0.9/s", "") == "rtsp://10.0.0.9/s"


def test_host_of() -> None:
    assert urls.host_of("http://cam.example:8000/x") == "cam.example"
    assert urls.host_of("garbage") == ""
