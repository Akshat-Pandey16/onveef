"""Shared fixtures and stubbing helpers for the onveef test-suite.

Every test drives the clients through their sans-IO seam: ``_post_soap`` is replaced with
a callable that returns canned ``(status, xml)`` pairs, so no test touches the network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from onveef.aclient import AsyncOnvifClient
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint

DEVICE_XADDR = "http://cam/onvif/device_service"

ALL_SERVICES = {
    "device": DEVICE_XADDR,
    "media": "http://cam/onvif/media",
    "media2": "http://cam/onvif/media2",
    "ptz": "http://cam/onvif/ptz",
    "imaging": "http://cam/onvif/imaging",
    "events": "http://cam/onvif/events",
    "analytics": "http://cam/onvif/analytics",
    "recording": "http://cam/onvif/recording",
    "search": "http://cam/onvif/search",
    "replay": "http://cam/onvif/replay",
    "deviceio": "http://cam/onvif/deviceio",
    "accesscontrol": "http://cam/onvif/accesscontrol",
    "doorcontrol": "http://cam/onvif/doorcontrol",
    "credential": "http://cam/onvif/credential",
}

Responder = Callable[[str], "tuple[int, str]"]


def make_client(
    services: dict[str, str] | None = None,
    *,
    credentials: OnvifCredentials | None = None,
    device_xaddr: str = DEVICE_XADDR,
    **kwargs: Any,
) -> OnvifClient:
    """Build an offline :class:`OnvifClient` with a fixed service map."""
    return OnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr=device_xaddr,
            services=dict(ALL_SERVICES if services is None else services),
        ),
        credentials=credentials or OnvifCredentials(),
        **kwargs,
    )


def make_async_client(
    services: dict[str, str] | None = None,
    *,
    credentials: OnvifCredentials | None = None,
    device_xaddr: str = DEVICE_XADDR,
    **kwargs: Any,
) -> AsyncOnvifClient:
    """Build an offline :class:`AsyncOnvifClient` with a fixed service map."""
    return AsyncOnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr=device_xaddr,
            services=dict(ALL_SERVICES if services is None else services),
        ),
        credentials=credentials or OnvifCredentials(),
        **kwargs,
    )


def stub(client: OnvifClient, responder: Responder | str) -> list[str]:
    """Replace the client's transport; return the list envelopes are captured into."""
    captured: list[str] = []
    reply: Responder = (
        (lambda _envelope: (200, responder)) if isinstance(responder, str) else responder
    )

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        captured.append(envelope)
        return reply(envelope)

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def stub_async(client: AsyncOnvifClient, responder: Responder | str) -> list[str]:
    """Async counterpart of :func:`stub`."""
    captured: list[str] = []
    reply: Responder = (
        (lambda _envelope: (200, responder)) if isinstance(responder, str) else responder
    )

    async def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        captured.append(envelope)
        return reply(envelope)

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def record_read_timeouts(client: OnvifClient, xml: str) -> list[float | None]:
    """Capture the ``read_timeout_s`` each request is issued with."""
    seen: list[float | None] = []

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        seen.append(read_timeout_s)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return seen


@pytest.fixture
def client() -> Iterator[OnvifClient]:
    """An offline sync client with every service advertised."""
    instance = make_client()
    yield instance
    instance.close()


@pytest.fixture
def async_client() -> AsyncOnvifClient:
    """An offline async client with every service advertised."""
    return make_async_client()
