"""End-to-end transport tests driven through ``httpx.MockTransport``.

These exercise the real request path — streaming, size caps, content-type negotiation,
status classification, HTTP auth challenges, retries and the circuit breaker — rather than
stubbing it out. They are only possible because the clients accept an injected transport.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from conftest import DEVICE_XADDR, make_async_client, make_client
from onveef.client import OnvifClient, OnvifCredentials
from onveef.exceptions import (
    OnvifAuthError,
    OnvifFaultError,
    OnvifOperationNotSupportedError,
    OnvifServiceUnavailableError,
    OnvifTimeoutError,
    OnvifTransportError,
)

_HOSTNAME = "<GetHostnameResponse><Name>cam</Name></GetHostnameResponse>"


def _fault(reason: str, subcode: str = "") -> str:
    sub = f"<s:Subcode><s:Value>{subcode}</s:Value></s:Subcode>" if subcode else ""
    return (
        "<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'><s:Body><s:Fault>"
        f"<s:Code><s:Value>s:Sender</s:Value>{sub}</s:Code>"
        f"<s:Reason><s:Text>{reason}</s:Text></s:Reason>"
        "</s:Fault></s:Body></s:Envelope>"
    )


def _client(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> OnvifClient:
    return make_client(transport=httpx.MockTransport(handler), **kwargs)


def test_happy_path_through_the_real_request_pipeline() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=_HOSTNAME)

    with _client(handler) as client:
        assert client.get_hostname() == "cam"
    assert seen[0].headers["content-type"] == "application/soap+xml; charset=utf-8"
    assert seen[0].headers["user-agent"].startswith("onveef/")


def test_content_type_negotiation_falls_back_to_text_xml() -> None:
    """Some firmware rejects application/soap+xml with a bare 415."""
    types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        types.append(request.headers["content-type"])
        if "soap+xml" in request.headers["content-type"]:
            return httpx.Response(415, text="unsupported")
        return httpx.Response(200, text=_HOSTNAME)

    with _client(handler) as client:
        assert client.get_hostname() == "cam"
    assert types == [
        "application/soap+xml; charset=utf-8",
        "text/xml; charset=utf-8",
    ]


def test_http_digest_challenge_is_answered() -> None:
    attempts: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        attempts.append(auth)
        if auth is None:
            return httpx.Response(
                401, headers={"WWW-Authenticate": 'Digest realm="cam", nonce="abc"'}
            )
        return httpx.Response(200, text=_HOSTNAME)

    with _client(handler, credentials=OnvifCredentials("admin", "pw")) as client:
        assert client.get_hostname() == "cam"
    assert attempts[0] is None
    assert attempts[-1] is not None
    assert attempts[-1].startswith("Digest ")


def test_http_basic_challenge_is_answered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        if auth is None:
            return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="cam"'})
        assert auth.startswith("Basic ")
        return httpx.Response(200, text=_HOSTNAME)

    with _client(handler, credentials=OnvifCredentials("admin", "pw")) as client:
        assert client.get_hostname() == "cam"


def test_http_auth_can_be_disabled() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="cam"'})

    with (
        _client(handler, credentials=OnvifCredentials("a", "b"), http_auth="none") as client,
        pytest.raises(OnvifAuthError),
    ):
        client.get_hostname()


def test_redirects_are_reported_not_followed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://cam/onvif/device_service"})

    with _client(handler) as client, pytest.raises(OnvifTransportError, match="redirected"):
        client.get_hostname()


def test_service_unavailable_is_retried_then_raised() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with _client(handler, retries=2) as client:
        client._backoff = lambda attempt: 0.0  # type: ignore[method-assign]
        with pytest.raises(OnvifServiceUnavailableError):
            client.get_hostname()
    assert len(calls) == 3


def test_a_transient_failure_then_success() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, text=_HOSTNAME)

    with _client(handler, retries=2) as client:
        client._backoff = lambda attempt: 0.0  # type: ignore[method-assign]
        assert client.get_hostname() == "cam"


def test_write_operations_are_not_retried() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with _client(handler, retries=3) as client, pytest.raises(OnvifServiceUnavailableError):
        client.set_hostname(name="cam2")
    assert len(calls) == 1


def test_soap_fault_is_classified_as_a_fault() -> None:
    with (
        _client(lambda _r: httpx.Response(200, text=_fault("Bad argument"))) as client,
        pytest.raises(OnvifFaultError, match="Bad argument"),
    ):
        client.get_hostname()


def test_not_authorized_fault_is_an_auth_error() -> None:
    with (
        _client(lambda _r: httpx.Response(200, text=_fault("NotAuthorized"))) as client,
        pytest.raises(OnvifAuthError),
    ):
        client.get_hostname()


def test_unsupported_fault_maps_to_operation_not_supported() -> None:
    body = _fault("Optional Action Not Implemented", "ter:ActionNotSupported")
    with (
        _client(lambda _r: httpx.Response(200, text=body)) as client,
        pytest.raises(OnvifOperationNotSupportedError),
    ):
        client.get_hostname()


def test_a_fault_carried_on_a_500_is_still_a_fault() -> None:
    with (
        _client(lambda _r: httpx.Response(500, text=_fault("Internal"))) as client,
        pytest.raises(OnvifFaultError),
    ):
        client.get_hostname()


def test_oversized_responses_are_capped() -> None:
    big = "<GetHostnameResponse>" + ("x" * 5000) + "</GetHostnameResponse>"
    with (
        _client(lambda _r: httpx.Response(200, text=big), max_response_bytes=1024) as client,
        pytest.raises(OnvifTransportError, match="cap"),
    ):
        client.get_hostname()


def test_connect_errors_become_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with (
        _client(handler, retries=0) as client,
        pytest.raises(OnvifTransportError, match="transport error"),
    ):
        client.get_hostname()


def test_timeouts_become_timeout_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with _client(handler, retries=0) as client, pytest.raises(OnvifTimeoutError):
        client.get_hostname()
    assert OnvifTimeoutError("x").retryable is True


def test_the_circuit_breaker_opens_and_short_circuits() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("down", request=request)

    with _client(handler, retries=0, breaker_key="cam-1", breaker_threshold=2) as client:
        for _ in range(2):
            with pytest.raises(OnvifTransportError):
                client.get_hostname()
        before = len(calls)
        with pytest.raises(OnvifTransportError, match="circuit breaker open"):
            client.get_hostname()
        assert len(calls) == before


def test_a_non_utf8_response_still_decodes() -> None:
    body = "<GetHostnameResponse><Name>café</Name></GetHostnameResponse>".encode("latin-1")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/xml; charset=iso-8859-1"}
        )

    with _client(handler) as client:
        assert client.get_hostname() == "café"


def test_service_discovery_rewrites_xaddrs_end_to_end() -> None:
    """The whole point: a device that reports its own LAN address stays reachable."""
    services = (
        "<GetServicesResponse>"
        "<Service><Namespace>http://www.onvif.org/ver10/media/wsdl</Namespace>"
        "<XAddr>http://192.168.1.64/onvif/media</XAddr></Service>"
        "<Service><Namespace>http://www.onvif.org/ver20/ptz/wsdl</Namespace>"
        "<XAddr>http://0.0.0.0/onvif/ptz</XAddr></Service>"
        "</GetServicesResponse>"
    )
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if b"GetServices" in request.content:
            return httpx.Response(200, text=services)
        return httpx.Response(200, text="<GetPresetsResponse/>")

    client = make_client(
        {},
        device_xaddr=DEVICE_XADDR,
        transport=httpx.MockTransport(handler),
        auto_discover=True,
    )
    with client:
        client.ptz_get_presets(profile_token="P0")
    assert urls[-1] == "http://cam/onvif/ptz"


async def test_async_transport_round_trip() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_HOSTNAME)

    client = make_async_client(transport=httpx.MockTransport(handler))
    async with client:
        assert await client.get_hostname() == "cam"


async def test_async_fault_classification() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_fault("NotAuthorized"))

    client = make_async_client(transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(OnvifAuthError):
            await client.get_hostname()


async def test_async_retry_then_success() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, text=_HOSTNAME)

    client = make_async_client(transport=httpx.MockTransport(handler), retries=2)
    client._backoff = lambda attempt: 0.0  # type: ignore[method-assign]
    async with client:
        assert await client.get_hostname() == "cam"


async def test_async_oversized_response_is_capped() -> None:
    big = "<GetHostnameResponse>" + ("x" * 5000) + "</GetHostnameResponse>"
    client = make_async_client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=big)),
        max_response_bytes=1024,
    )
    async with client:
        with pytest.raises(OnvifTransportError, match="cap"):
            await client.get_hostname()
