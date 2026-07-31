"""Tests for the managed pull-point subscriptions (sync and async)."""

from __future__ import annotations

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef.exceptions import OnvifFaultError

_CREATE = (
    "<CreatePullPointSubscriptionResponse><SubscriptionReference>"
    "<Address>http://192.168.9.9/onvif/sub?id=1</Address>"
    "</SubscriptionReference><CurrentTime>t0</CurrentTime>"
    "<TerminationTime>t1</TerminationTime></CreatePullPointSubscriptionResponse>"
)
_MESSAGES = (
    "<PullMessagesResponse><NotificationMessage>"
    "<Topic>tns1:RuleEngine/Motion</Topic>"
    '<Message><Message UtcTime="2026-01-01T00:00:00Z" PropertyOperation="Changed">'
    '<Source><SimpleItem Name="Rule" Value="R1"/></Source>'
    '<Data><SimpleItem Name="IsMotion" Value="true"/></Data>'
    "</Message></Message></NotificationMessage></PullMessagesResponse>"
)
_EMPTY = "<PullMessagesResponse/>"
_FAULT = (
    "<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'><s:Body><s:Fault>"
    "<s:Code><s:Value>s:Sender</s:Value></s:Code>"
    "<s:Reason><s:Text>Subscription not found</s:Text></s:Reason>"
    "</s:Fault></s:Body></s:Envelope>"
)


def test_subscription_url_is_host_rewritten() -> None:
    """The device reports its own LAN address; it must be re-pointed at the one we used."""
    client = make_client()
    stub(client, _CREATE)
    result = client.events_create_pull_point()
    assert result["subscription_url"] == "http://cam/onvif/sub?id=1"


def test_rewriting_can_be_disabled() -> None:
    client = make_client(rewrite_host=False)
    stub(client, _CREATE)
    result = client.events_create_pull_point()
    assert result["subscription_url"] == "http://192.168.9.9/onvif/sub?id=1"


def test_pull_point_creates_pulls_and_unsubscribes() -> None:
    client = make_client()

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        if "PullMessages" in envelope:
            return 200, _MESSAGES
        return 200, "<UnsubscribeResponse/>"

    sent = stub(client, responder)
    with client.pull_point(topic_filter="tns1:RuleEngine//.") as subscription:
        assert subscription.active
        messages = subscription.pull()

    assert messages[0]["topic"] == "tns1:RuleEngine/Motion"
    assert messages[0]["data"] == {"IsMotion": "true"}
    assert any("CreatePullPointSubscription" in e for e in sent)
    assert any("Unsubscribe" in e for e in sent)
    assert not subscription.active


def test_pull_point_recreates_when_the_device_forgot_the_subscription() -> None:
    """Devices expire pull-points; a fault on pull should transparently re-subscribe."""
    client = make_client()
    state = {"pulls": 0, "creates": 0}

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            state["creates"] += 1
            return 200, _CREATE
        if "PullMessages" in envelope:
            state["pulls"] += 1
            if state["pulls"] == 1:
                return 200, _FAULT
            return 200, _MESSAGES
        return 200, "<UnsubscribeResponse/>"

    stub(client, responder)
    subscription = client.pull_point(auto_renew=False)
    messages = subscription.pull()
    assert state["creates"] == 2
    assert messages[0]["topic"] == "tns1:RuleEngine/Motion"


def test_pull_point_renews_when_the_interval_elapses() -> None:
    client = make_client()
    renews: list[str] = []

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        if "Renew" in envelope:
            renews.append(envelope)
            return 200, "<RenewResponse/>"
        return 200, _EMPTY

    stub(client, responder)
    subscription = client.pull_point(termination_time="PT60S")
    subscription._renew_at = 0.0
    subscription.pull()
    assert len(renews) == 1
    assert "PT60S" in renews[0]


def test_unsubscribe_swallows_a_device_that_already_forgot() -> None:
    client = make_client()

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        return 200, _FAULT

    stub(client, responder)
    subscription = client.pull_point()
    subscription.unsubscribe()
    assert not subscription.active


def test_create_without_a_reference_raises() -> None:
    client = make_client()
    stub(client, "<CreatePullPointSubscriptionResponse/>")
    with pytest.raises(OnvifFaultError, match="no reference"):
        client.pull_point()


def test_iteration_yields_messages() -> None:
    client = make_client()

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        if "PullMessages" in envelope:
            return 200, _MESSAGES
        return 200, "<UnsubscribeResponse/>"

    stub(client, responder)
    with client.pull_point() as subscription:
        collected = []
        for message in subscription:
            collected.append(message)
            if len(collected) == 3:
                break
    assert len(collected) == 3


async def test_async_pull_point_round_trip() -> None:
    client = make_async_client()

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        if "PullMessages" in envelope:
            return 200, _MESSAGES
        return 200, "<UnsubscribeResponse/>"

    sent = stub_async(client, responder)
    async with client.pull_point(topic_filter="tns1:RuleEngine//.") as subscription:
        assert subscription.subscription_url == "http://cam/onvif/sub?id=1"
        messages = await subscription.pull()

    assert messages[0]["source"] == {"Rule": "R1"}
    assert any("Unsubscribe" in e for e in sent)


async def test_async_iteration_yields_messages() -> None:
    client = make_async_client()

    def responder(envelope: str) -> tuple[int, str]:
        if "CreatePullPointSubscription" in envelope:
            return 200, _CREATE
        if "PullMessages" in envelope:
            return 200, _MESSAGES
        return 200, "<UnsubscribeResponse/>"

    stub_async(client, responder)
    collected = []
    async with client.pull_point() as subscription:
        async for message in subscription:
            collected.append(message)
            if len(collected) == 2:
                break
    assert len(collected) == 2


async def test_async_pull_messages_uses_a_scoped_read_timeout() -> None:
    client = make_async_client()
    seen: list[float | None] = []

    async def fake_post_soap(
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        seen.append(read_timeout_s)
        return 200, _EMPTY if "PullMessages" in envelope else "<GetHostnameResponse/>"

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    await client.events_pull_messages(subscription_url="http://cam/sub", timeout="PT20S")
    await client.get_hostname()
    assert seen == [25.0, None]
