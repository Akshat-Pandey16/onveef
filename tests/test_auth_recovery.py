"""Logins a device wrongly refuses: clock skew, HTTP Digest, and how cameras say "no".

The fake camera below is modelled on a CP Plus (Dahua OEM) unit: it checks the
WS-Security ``Created`` stamp against its own clock on *every* request it authenticates —
including ``GetSystemDateAndTime``, the very call that measures the skew — and answers a
refused login with HTTP 400 and ``ter:NotAuthorized`` / "…the sender is not authorized",
a reason that matches neither ``NotAuthorized`` nor ``Sender not Authorized`` literally.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from onveef import parsers
from onveef.aclient import AsyncOnvifClient
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint
from onveef.exceptions import OnvifAuthError, OnvifFaultError

_DEVICE = "http://cam/onvif/device_service"
_PASSWORD = "Lediscet@123"
_REALM = "Login to 4b1f"
_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tt="http://www.onvif.org/ver10/schema" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
    'xmlns:ter="http://www.onvif.org/ver10/error"><s:Body>{body}</s:Body></s:Envelope>'
)
_NOT_AUTHORIZED = (
    "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NotAuthorized"
    '</s:Value></s:Subcode></s:Code><s:Reason><s:Text xml:lang="en">The action requested '
    "requires authorization and the sender is not authorized</s:Text></s:Reason></s:Fault>"
)


def _md5(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


class FakeCamera:
    """A camera with its own clock that checks every login it is sent."""

    def __init__(
        self, *, ahead_s: float = 0.0, digest_only: bool = False, password: str = _PASSWORD
    ) -> None:
        self.ahead_s = ahead_s
        self.digest_only = digest_only
        self.password = password
        self.nonce = uuid.uuid4().hex
        self.requests: list[httpx.Request] = []

    def operations(self) -> list[str]:
        return [self._operation(request) for request in self.requests]

    @staticmethod
    def _operation(request: httpx.Request) -> str:
        match = re.search(r"<s:Body><(?:\w+:)?(\w+)", request.content.decode())
        return match.group(1) if match else ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = request.content.decode()
        now = datetime.now(timezone.utc) + timedelta(seconds=self.ahead_s)
        operation = self._operation(request)
        if operation == "GetSystemDateAndTime" and "UsernameToken" not in body:
            return self._soap(
                "<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:UTCDateTime>"
                f"<tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute>"
                f"<tt:Second>{now.second}</tt:Second></tt:Time><tt:Date><tt:Year>{now.year}"
                f"</tt:Year><tt:Month>{now.month}</tt:Month><tt:Day>{now.day}</tt:Day></tt:Date>"
                "</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>"
            )
        authorized = (
            self._digest_ok(request) if self.digest_only else self._ws_security_ok(body, now)
        )
        if authorized:
            return self._soap(
                "<tds:GetDeviceInformationResponse><tds:Manufacturer>CP PLUS</tds:Manufacturer>"
                "<tds:Model>CP-UNC-TA21PL3</tds:Model></tds:GetDeviceInformationResponse>"
            )
        if self.digest_only:
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        f'Digest realm="{_REALM}",qop="auth", algorithm="MD5", '
                        f'nonce="{self.nonce}", opaque="", stale="false"'
                    )
                },
            )
        return self._soap(_NOT_AUTHORIZED, status=400)

    @staticmethod
    def _soap(body: str, status: int = 200) -> httpx.Response:
        return httpx.Response(
            status,
            text=_ENVELOPE.format(body=body),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        )

    def _ws_security_ok(self, body: str, now: datetime) -> bool:
        nonce = re.search(r"<wsse:Nonce[^>]*>([^<]+)<", body)
        created = re.search(r"<wsu:Created>([^<]+)<", body)
        digest = re.search(r"<wsse:Password[^>]*>([^<]+)<", body)
        if not (nonce and created and digest):
            return False
        expected = hashlib.sha1(
            base64.b64decode(nonce.group(1)) + created.group(1).encode() + self.password.encode(),
            usedforsecurity=False,
        ).digest()
        stamp = datetime.strptime(created.group(1), "%Y-%m-%dT%H:%M:%S.000Z").replace(
            tzinfo=timezone.utc
        )
        fresh = abs((stamp - now).total_seconds()) <= 5
        return fresh and base64.b64encode(expected).decode() == digest.group(1)

    def _digest_ok(self, request: httpx.Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        fields = dict(re.findall(r'(\w+)="?([^",]*)"?', header[len("Digest ") :]))
        ha1 = _md5(f"{fields.get('username')}:{_REALM}:{self.password}")
        ha2 = _md5(f"POST:{fields.get('uri')}")
        expected = _md5(
            f"{ha1}:{fields.get('nonce')}:{fields.get('nc')}:{fields.get('cnonce')}:"
            f"{fields.get('qop')}:{ha2}"
        )
        return fields.get("username") == "admin" and fields.get("response") == expected


def _client(camera: FakeCamera, **kwargs: object) -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        credentials=OnvifCredentials("admin", _PASSWORD),
        transport=httpx.MockTransport(camera.handler),
        **kwargs,  # type: ignore[arg-type]
    )


def _async_client(camera: FakeCamera, **kwargs: object) -> AsyncOnvifClient:
    return AsyncOnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        credentials=OnvifCredentials("admin", _PASSWORD),
        transport=httpx.MockTransport(camera.handler),
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_camera_refusal_is_recognised_as_an_auth_error() -> None:
    """HTTP 400 + "…the sender is not authorized" used to surface as a generic fault."""
    assert parsers.fault_is_auth(_ENVELOPE.format(body=_NOT_AUTHORIZED))


@pytest.mark.parametrize(
    "fault",
    [
        "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>"
        "wsse:FailedAuthentication</s:Value></s:Subcode></s:Code><s:Reason><s:Text>"
        "The security token could not be authenticated or authorized</s:Text></s:Reason>"
        "</s:Fault>",
        "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>"
        "wsse:InvalidSecurity</s:Value></s:Subcode></s:Code><s:Reason><s:Text>"
        "An error was discovered processing the header</s:Text></s:Reason></s:Fault>",
        "<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code><s:Reason>"
        "<s:Text>Sender not Authorized</s:Text></s:Reason></s:Fault>",
    ],
)
def test_every_spelling_of_a_refused_login_is_an_auth_error(fault: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=_ENVELOPE.format(body=fault))

    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        transport=httpx.MockTransport(handler),
    )
    with client, pytest.raises(OnvifAuthError):
        client.get_hostname()


def test_a_fault_that_is_not_about_the_login_is_still_a_fault() -> None:
    fault = (
        "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:InvalidArgVal"
        "</s:Value></s:Subcode></s:Code><s:Reason><s:Text>Bad hostname</s:Text></s:Reason>"
        "</s:Fault>"
    )
    assert not parsers.fault_is_auth(_ENVELOPE.format(body=fault))
    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(400, text=_ENVELOPE.format(body=fault))
        ),
    )
    with client, pytest.raises(OnvifFaultError):
        client.set_hostname("x y")


def test_clock_resync_reads_the_camera_time_without_credentials() -> None:
    """The clock read must not carry the very WS-Security stamp the device is refusing."""
    camera = FakeCamera(ahead_s=60)
    resyncs: list[float] = []
    with _client(camera, on_clock_resync=resyncs.append) as client:
        assert client.get_device_information()["Manufacturer"] == "CP PLUS"
        assert client.clock_offset_s == pytest.approx(60, abs=2)
    assert camera.operations() == [
        "GetDeviceInformation",
        "GetSystemDateAndTime",
        "GetDeviceInformation",
    ]
    assert "UsernameToken" not in camera.requests[1].content.decode()
    assert resyncs == [pytest.approx(60, abs=2)]


async def test_async_clock_resync_reads_the_camera_time_without_credentials() -> None:
    camera = FakeCamera(ahead_s=-3600)
    resyncs: list[float] = []
    async with _async_client(camera, on_clock_resync=resyncs.append) as client:
        assert (await client.get_device_information())["Manufacturer"] == "CP PLUS"
        assert client.clock_offset_s == pytest.approx(-3600, abs=2)
    assert camera.operations() == [
        "GetDeviceInformation",
        "GetSystemDateAndTime",
        "GetDeviceInformation",
    ]
    assert resyncs == [pytest.approx(-3600, abs=2)]


def test_a_known_clock_offset_needs_no_failed_login() -> None:
    camera = FakeCamera(ahead_s=60)
    with _client(camera, clock_offset_s=60) as client:
        client.get_device_information()
    assert camera.operations() == ["GetDeviceInformation"]


async def test_async_known_clock_offset_needs_no_failed_login() -> None:
    camera = FakeCamera(ahead_s=60)
    async with _async_client(camera, clock_offset_s=60) as client:
        await client.get_device_information()
    assert camera.operations() == ["GetDeviceInformation"]


def test_rejected_credentials_cost_one_clock_read_and_no_second_login() -> None:
    """With the clock already right, a refused login is not retried (lockout risk)."""
    camera = FakeCamera(password="different")
    with _client(camera) as client, pytest.raises(OnvifAuthError):
        client.get_device_information()
    assert camera.operations() == ["GetDeviceInformation", "GetSystemDateAndTime"]


def test_the_clock_is_read_at_most_once_a_minute_on_repeated_refusals() -> None:
    camera = FakeCamera(password="different")
    with _client(camera) as client:
        for _ in range(3):
            with pytest.raises(OnvifAuthError):
                client.get_device_information()
    assert camera.operations().count("GetSystemDateAndTime") == 1


def test_a_long_lived_client_follows_a_clock_that_jumps_later() -> None:
    """A camera's clock moves after a reboot's NTP sync: the old offset must not stick."""
    camera = FakeCamera(ahead_s=60)
    with _client(camera) as client:
        client.get_device_information()
        camera.ahead_s = 600
        client._clock_checked_at -= 120  # the last clock read was over a minute ago
        assert client.get_device_information()["Manufacturer"] == "CP PLUS"
        assert client.clock_offset_s == pytest.approx(600, abs=2)


def test_http_digest_is_answered_up_front_once_the_device_asked_for_it() -> None:
    """A digest-only device used to cost a 401 round trip on every single request."""
    camera = FakeCamera(digest_only=True)
    with _client(camera) as client:
        client.get_device_information()
        first = len(camera.requests)
        client.get_device_information()
    later = camera.requests[first:]
    assert len(later) == 1
    assert later[0].headers["Authorization"].startswith("Digest ")


async def test_async_http_digest_is_answered_up_front() -> None:
    camera = FakeCamera(digest_only=True)
    async with _async_client(camera) as client:
        await client.get_device_information()
        first = len(camera.requests)
        await client.get_device_information()
    assert len(camera.requests) == first + 1


def test_plaintext_fallback_sticks_once_the_device_accepts_it() -> None:
    """Re-trying the digest first on every call hands the device a failed login each time."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        sent.append(body)
        if "#PasswordText" in body or "GetSystemDateAndTime" in body:
            return httpx.Response(
                200, text="<GetHostnameResponse><Name>cam</Name></GetHostnameResponse>"
            )
        return httpx.Response(400, text=_ENVELOPE.format(body=_NOT_AUTHORIZED))

    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        credentials=OnvifCredentials("admin", "pw"),
        password_text_fallback=True,
        transport=httpx.MockTransport(handler),
    )
    with client:
        assert client.get_hostname() == "cam"
        before = len(sent)
        assert client.get_hostname() == "cam"
    assert len(sent) == before + 1
    assert "#PasswordText" in sent[-1]


def test_subscription_requests_recover_from_clock_skew_too() -> None:
    camera = FakeCamera(ahead_s=90)
    pulled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/subscription"):
            body = request.content.decode()
            if not camera._ws_security_ok(body, datetime.now(timezone.utc) + timedelta(seconds=90)):
                return FakeCamera._soap(_NOT_AUTHORIZED, status=400)
            pulled.append(body)
            return httpx.Response(200, text="<PullMessagesResponse/>")
        return camera.handler(request)

    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=_DEVICE, services={"device": _DEVICE}),
        credentials=OnvifCredentials("admin", _PASSWORD),
        transport=httpx.MockTransport(handler),
    )
    with client:
        client.events_pull_messages(subscription_url="http://cam/subscription")
        assert client.clock_offset_s == pytest.approx(90, abs=2)
    assert len(pulled) == 1


def test_a_client_signs_with_a_fresh_offset_after_another_call_fixed_it() -> None:
    """A request refused on a stale offset retries if a concurrent call already corrected it."""
    client = _client(FakeCamera())
    client._clock_offset_s = 60.0
    assert client._resync_clock(used_offset=0.0) is True
    client._clock_checked_at = time.monotonic()
    assert client._resync_clock(used_offset=60.0) is False
