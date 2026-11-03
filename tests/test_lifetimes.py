"""Subscription lifetimes the device grants, and requests a device may hold open."""

from __future__ import annotations

import pytest

from conftest import make_async_client, make_client, record_read_timeouts, stub, stub_async
from onveef import parsers

_CREATED = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
    "<CreatePullPointSubscriptionResponse>"
    "<SubscriptionReference><Address>http://cam/onvif/sub</Address></SubscriptionReference>"
    "<CurrentTime>{current}</CurrentTime><TerminationTime>{termination}</TerminationTime>"
    "</CreatePullPointSubscriptionResponse></s:Body></s:Envelope>"
)
_RENEWED = (
    "<RenewResponse><TerminationTime>2026-07-02T12:00:30Z</TerminationTime>"
    "<CurrentTime>2026-07-02T12:00:00Z</CurrentTime></RenewResponse>"
)


@pytest.mark.parametrize(
    ("current", "termination", "lifetime"),
    [
        ("2026-07-02T12:00:00Z", "2026-07-02T12:00:10Z", 10.0),
        ("2026-07-02T12:00:00.5Z", "2026-07-02T12:01:00.5Z", 60.0),
        ("2026-07-02T17:30:00+05:30", "2026-07-02T12:00:20Z", 20.0),
        ("2026-07-02T12:00:00", "2026-07-02T12:00:05", 5.0),
        ("", "2026-07-02T12:00:05Z", None),
        ("garbage", "2026-07-02T12:00:05Z", None),
    ],
)
def test_the_granted_lifetime_is_read_on_the_devices_own_clock(
    current: str, termination: str, lifetime: float | None
) -> None:
    result = parsers.parse_create_pull_point(
        _CREATED.format(current=current, termination=termination)
    )
    assert result["lifetime_s"] == lifetime


def test_a_renewal_reports_its_new_lifetime() -> None:
    assert parsers.parse_renew(_RENEWED) == {
        "current_time": "2026-07-02T12:00:00Z",
        "termination_time": "2026-07-02T12:00:30Z",
        "lifetime_s": 30.0,
    }
    assert parsers.parse_renew("<nope")["lifetime_s"] is None


def _device_granting(seconds: int) -> object:
    created = _CREATED.format(
        current="2026-07-02T12:00:00Z", termination=f"2026-07-02T12:00:{seconds:02d}Z"
    )

    def respond(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, created
        if "RenewRequest" in envelope:
            return 200, _RENEWED
        return 200, "<PullMessagesResponse/>"

    return respond


def test_a_capped_lifetime_shortens_renewals_and_polls() -> None:
    """Asked for 60 s and granted 9: renewing at 30 s would let it lapse every time."""
    client = make_client()
    sent = stub(client, _device_granting(9))  # type: ignore[arg-type]
    with client.pull_point(termination_time="PT60S", timeout="PT5S") as subscription:
        assert subscription._renew_interval_s == 4.5
        subscription.pull()
    pulls = [e for e in sent if "PullMessagesRequest" in e]
    assert "<tev:Timeout>PT3S</tev:Timeout>" in pulls[0]


def test_a_renewal_reschedules_from_what_the_device_granted_then() -> None:
    client = make_client()
    stub(client, _device_granting(9))  # type: ignore[arg-type]
    subscription = client.pull_point(termination_time="PT60S")
    subscription.renew()
    assert subscription._renew_interval_s == 15.0
    assert subscription._pull_timeout == "PT5S"


async def test_async_a_capped_lifetime_shortens_renewals_and_polls() -> None:
    client = make_async_client()
    sent = stub_async(client, _device_granting(9))  # type: ignore[arg-type]
    async with client.pull_point(termination_time="PT60S") as subscription:
        assert subscription._renew_interval_s == 4.5
        await subscription.pull()
        await subscription.renew()
        assert subscription._renew_interval_s == 15.0
    assert "<tev:Timeout>PT3S</tev:Timeout>" in next(e for e in sent if "PullMessagesRequest" in e)


def test_an_uncapped_lifetime_keeps_the_requested_schedule() -> None:
    client = make_client()
    stub(client, _device_granting(59))  # type: ignore[arg-type]
    subscription = client.pull_point(termination_time="PT60S", timeout="PT5S")
    assert subscription._pull_timeout == "PT5S"
    assert subscription._renew_interval_s == 29.5


def test_events_renew_returns_the_granted_lifetime() -> None:
    client = make_client()
    stub(client, _RENEWED)
    assert client.events_renew(subscription_url="http://cam/onvif/sub")["lifetime_s"] == 30.0


@pytest.mark.parametrize(
    "method",
    [
        "get_recording_search_results",
        "get_event_search_results",
        "get_ptz_position_search_results",
        "get_metadata_search_results",
    ],
)
def test_search_results_may_be_held_for_their_whole_wait_time(method: str) -> None:
    """With WaitTime equal to the read timeout, a device that waits it out raced the timeout."""
    client = make_client()
    seen = record_read_timeouts(client, "<GetRecordingSearchResultsResponse/>")
    getattr(client, method)(search_token="S1", wait_time="PT20S")
    assert seen == [25.0]


async def test_async_search_results_may_be_held_for_their_whole_wait_time() -> None:
    client = make_async_client()
    seen: list[float | None] = []

    async def fake_post_soap(
        *, url: str, envelope: str, content_type: str, read_timeout_s: float | None = None
    ) -> tuple[int, str]:
        seen.append(read_timeout_s)
        return 200, "<GetEventSearchResultsResponse/>"

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    await client.get_event_search_results(search_token="S1", wait_time="PT1M")
    assert seen == [65.0]


def test_a_long_poll_never_shortens_a_longer_configured_read_timeout() -> None:
    client = make_client(read_timeout_s=30.0)
    seen = record_read_timeouts(client, "<PullMessagesResponse/>")
    client.events_pull_messages(subscription_url="http://cam/onvif/sub", timeout="PT5S")
    assert seen == [30.0]


def test_a_non_blocking_poll_stays_non_blocking() -> None:
    client = make_client()
    sent = stub(client, _device_granting(9))  # type: ignore[arg-type]
    with client.pull_point(termination_time="PT60S", timeout="PT0S") as subscription:
        subscription.pull()
    assert "<tev:Timeout>PT0S</tev:Timeout>" in next(e for e in sent if "PullMessagesRequest" in e)
