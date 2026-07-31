"""Tests for the per-request read timeout and the locking around lazy discovery."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from conftest import (
    ALL_SERVICES,
    DEVICE_XADDR,
    make_async_client,
    make_client,
    record_read_timeouts,
    stub,
)
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint
from onveef.exceptions import OnvifError

_HOSTNAME = "<GetHostnameResponse><Name>cam</Name></GetHostnameResponse>"
_PULL = "<PullMessagesResponse><CurrentTime>t</CurrentTime></PullMessagesResponse>"


def _no_backoff(attempt: int) -> float:
    """Drop the retry sleep so retry tests stay fast."""
    return 0.0


def test_ordinary_calls_use_the_default_read_timeout() -> None:
    client = make_client()
    seen = record_read_timeouts(client, _HOSTNAME)
    client.get_hostname()
    assert seen == [None]


def test_pull_messages_extends_only_its_own_read_timeout() -> None:
    """A long poll must not leave the extended timeout behind for the next caller."""
    client = make_client()
    seen = record_read_timeouts(client, _PULL)
    client.events_pull_messages(subscription_url="http://cam/sub", timeout="PT60S")
    assert seen == [65.0]

    after = record_read_timeouts(client, _HOSTNAME)
    client.get_hostname()
    assert after == [None]


def test_concurrent_call_during_a_long_poll_keeps_its_own_timeout() -> None:
    """The bug this guards: instance-level timeout state leaking across threads."""
    client = make_client()
    started = threading.Event()
    release = threading.Event()
    seen: list[tuple[str, float | None]] = []

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        if "PullMessages" in envelope:
            seen.append(("pull", read_timeout_s))
            started.set()
            release.wait(timeout=5)
            return 200, _PULL
        seen.append(("other", read_timeout_s))
        return 200, _HOSTNAME

    client._post_soap = fake_post_soap  # type: ignore[method-assign]

    poller = threading.Thread(
        target=lambda: client.events_pull_messages(
            subscription_url="http://cam/sub", timeout="PT30S"
        )
    )
    poller.start()
    assert started.wait(timeout=5)
    client.get_hostname()
    release.set()
    poller.join(timeout=5)

    assert ("pull", 35.0) in seen
    assert ("other", None) in seen


def test_retries_stay_enabled_for_calls_made_during_a_long_poll() -> None:
    """``max_attempts`` used to collapse to 1 for every concurrent call."""
    client = make_client(retries=2)
    attempts: list[str] = []

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        attempts.append(envelope)
        if len(attempts) == 1:
            return 503, ""
        return 200, _HOSTNAME

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    client._backoff = _no_backoff  # type: ignore[method-assign]
    assert client.get_hostname() == "cam"
    assert len(attempts) == 2


def test_pull_messages_does_not_retry() -> None:
    """Retrying a long poll would double-consume the device's message queue."""
    client = make_client(retries=3)
    attempts: list[str] = []

    def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        attempts.append(envelope)
        return 503, ""

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    client._backoff = _no_backoff  # type: ignore[method-assign]
    with contextlib.suppress(OnvifError):
        client.events_pull_messages(subscription_url="http://cam/sub")
    assert len(attempts) == 1


def test_discovery_runs_once_under_concurrent_threads() -> None:
    """The second thread must see the discovered map, not an empty one."""
    calls: list[int] = []
    barrier = threading.Barrier(4)

    client = OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr=DEVICE_XADDR),
        credentials=OnvifCredentials(),
        auto_discover=True,
    )

    def fake_discover() -> dict[str, str]:
        calls.append(1)
        threading.Event().wait(0.05)
        return dict(ALL_SERVICES)

    client.discover_services = fake_discover  # type: ignore[method-assign]

    resolved: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            resolved.append(client.require("ptz"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert len(calls) == 1
    assert resolved == ["http://cam/onvif/ptz"] * 4


def test_async_discovery_runs_once_under_concurrent_tasks() -> None:
    calls: list[int] = []

    async def scenario() -> list[str]:
        client = make_async_client({})
        client._auto_discover = True
        client._endpoint = OnvifEndpoint(device_xaddr=DEVICE_XADDR)

        async def fake_discover() -> dict[str, str]:
            calls.append(1)
            await asyncio.sleep(0.05)
            return dict(ALL_SERVICES)

        client.discover_services = fake_discover  # type: ignore[method-assign]

        async def resolve() -> str:
            await client._ensure("ptz")
            return client.require("ptz")

        return list(await asyncio.gather(*(resolve() for _ in range(4))))

    assert asyncio.run(scenario()) == ["http://cam/onvif/ptz"] * 4
    assert len(calls) == 1


def test_supplied_http_client_is_not_closed() -> None:
    import httpx

    shared = httpx.Client()
    client = make_client(http_client=shared)
    client.close()
    assert not shared.is_closed
    shared.close()


def test_owned_http_client_is_closed() -> None:
    client = make_client()
    client.close()
    assert client._client.is_closed


def test_repr_hides_the_password() -> None:
    client = make_client(credentials=OnvifCredentials("admin", "hunter2"))
    text = repr(client)
    assert "hunter2" not in text
    assert "admin" in text
    stub(client, _HOSTNAME)
