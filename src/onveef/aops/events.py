"""Events operations for the asyncio ONVIF client."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

from onveef import envelopes, parsers
from onveef.atransport import AsyncTransport
from onveef.exceptions import (
    OnvifError,
    OnvifFaultError,
    OnvifOperationNotSupportedError,
)
from onveef.transport import (
    _iso8601_seconds,
)

logger = logging.getLogger("onveef")


class EventOperations(AsyncTransport):
    """Events operations, mixed into :class:`~onveef.aclient.AsyncOnvifClient`."""

    async def events_get_event_properties(self) -> dict[str, Any]:
        """Return the device's event properties (topic set, message content, ...)."""
        xml = await self.call(
            service="events",
            operation="GetEventProperties",
            body_inner=envelopes.events_get_event_properties(),
        )
        return parsers.parse_event_properties(xml)

    async def events_create_pull_point(
        self, *, termination_time: str = "PT60S", topic_filter: str = ""
    ) -> dict[str, Any]:
        """Create a pull-point subscription and return its manager URL/times.

        The ``subscription_url`` is host-rewritten like any other device-reported address.
        Prefer :meth:`pull_point`, which keeps the subscription alive for you.
        """
        xml = await self.call(
            service="events",
            operation="CreatePullPointSubscription",
            body_inner=envelopes.events_create_pull_point_subscription(
                termination_time=termination_time, topic_filter=topic_filter
            ),
        )
        result = parsers.parse_create_pull_point(xml)
        if result.get("subscription_url"):
            result["subscription_url"] = self._fix_url(str(result["subscription_url"]))
        return result

    def pull_point(
        self,
        *,
        termination_time: str = "PT60S",
        topic_filter: str = "",
        timeout: str = "PT5S",
        message_limit: int = 20,
        auto_renew: bool = True,
    ) -> AsyncPullPointSubscription:
        """Return a managed pull-point subscription that renews and cleans up after itself.

        Use it as an async context manager; iteration blocks in the device's long poll::

            async with cam.pull_point(topic_filter="tns1:RuleEngine//.") as sub:
                async for message in sub:
                    print(message["topic"], message["data"])

        Unlike the sync helper this does not create the subscription eagerly — entering the
        ``async with`` block does, since creation needs to await.
        """
        return AsyncPullPointSubscription(
            self,
            termination_time=termination_time,
            topic_filter=topic_filter,
            timeout=timeout,
            message_limit=message_limit,
            auto_renew=auto_renew,
        )

    async def events_subscribe(
        self, *, consumer_address: str, topic_filter: str = "", termination_time: str = "PT60S"
    ) -> dict[str, Any]:
        """Create a WS-BaseNotification push subscription delivering to ``consumer_address``.

        The device POSTs a ``Notify`` envelope to ``consumer_address`` whenever an event
        matching ``topic_filter`` fires; decode those POST bodies with
        :func:`onveef.parsers.parse_notification`. Returns the subscription manager's
        ``subscription_url`` (host-rewritten, so it survives NAT) along with
        ``current_time`` and ``termination_time`` — renew it with :meth:`events_renew`
        before that deadline or the device drops the subscription, and tear it down with
        :meth:`events_unsubscribe`.

        You are responsible for the consumer: it must be an HTTP endpoint the *device*
        can reach, which is the usual reason to prefer :meth:`pull_point` when the client
        sits behind NAT.
        """
        xml = await self.call(
            service="events",
            operation="Subscribe",
            body_inner=envelopes.events_subscribe(
                consumer_address=consumer_address,
                topic_filter=topic_filter,
                termination_time=termination_time,
            ),
        )
        result = parsers.parse_subscribe(xml)
        if result.get("subscription_url"):
            result["subscription_url"] = self._fix_url(str(result["subscription_url"]))
        return result

    async def events_pull_messages(
        self,
        *,
        subscription_url: str,
        timeout: str = "PT5S",
        message_limit: int = 20,
    ) -> dict[str, Any]:
        """Long-poll a pull-point subscription for notification messages."""
        xml = await self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_pull_messages(timeout=timeout, message_limit=message_limit),
            wsa_action=(
                "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
            ),
            operation="PullMessages",
            read_timeout_s=_iso8601_seconds(timeout, 5.0) + 5.0,
        )
        return parsers.parse_pull_messages(xml)

    async def events_renew(self, *, subscription_url: str, termination_time: str = "PT60S") -> None:
        """Renew a subscription's termination time."""
        await self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_renew(termination_time=termination_time),
            wsa_action="http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest",
            operation="Renew",
        )

    async def events_unsubscribe(self, *, subscription_url: str) -> None:
        """Unsubscribe from a subscription."""
        await self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_unsubscribe(),
            wsa_action=(
                "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest"
            ),
            operation="Unsubscribe",
        )

    async def events_set_synchronization_point(self, *, subscription_url: str) -> None:
        """Request a synchronization point on a pull-point subscription."""
        await self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_set_synchronization_point(),
            wsa_action=(
                "http://www.onvif.org/ver10/events/wsdl/"
                "PullPointSubscription/SetSynchronizationPointRequest"
            ),
            operation="SetSynchronizationPoint",
        )


class AsyncPullPointSubscription:
    """An asyncio pull-point subscription that renews itself and tidies up on exit.

    The async counterpart of :class:`~onveef.client.PullPointSubscription`. Build one with
    :meth:`AsyncOnvifClient.pull_point` rather than directly.
    """

    def __init__(
        self,
        client: EventOperations,
        *,
        termination_time: str = "PT60S",
        topic_filter: str = "",
        timeout: str = "PT5S",
        message_limit: int = 20,
        auto_renew: bool = True,
    ) -> None:
        self._client = client
        self._termination_time = termination_time
        self._topic_filter = topic_filter
        self._timeout = timeout
        self._message_limit = message_limit
        self._auto_renew = auto_renew
        self._renew_interval_s = max(1.0, _iso8601_seconds(termination_time, 60.0) / 2)
        self._renew_at = 0.0
        self.subscription_url = ""

    @property
    def active(self) -> bool:
        """Whether a subscription reference is currently held."""
        return bool(self.subscription_url)

    async def create(self) -> str:
        """Create (or re-create) the subscription and return its reference URL."""
        result = await self._client.events_create_pull_point(
            termination_time=self._termination_time, topic_filter=self._topic_filter
        )
        url = str(result.get("subscription_url") or "")
        if not url:
            raise OnvifFaultError("Device returned a pull-point subscription with no reference.")
        self.subscription_url = url
        self._renew_at = time.monotonic() + self._renew_interval_s
        return url

    async def renew(self) -> None:
        """Extend the subscription's termination time."""
        if not self.subscription_url:
            return
        await self._client.events_renew(
            subscription_url=self.subscription_url, termination_time=self._termination_time
        )
        self._renew_at = time.monotonic() + self._renew_interval_s

    async def unsubscribe(self) -> None:
        """Cancel the subscription, ignoring a device that has already forgotten it."""
        url, self.subscription_url = self.subscription_url, ""
        if not url:
            return
        try:
            await self._client.events_unsubscribe(subscription_url=url)
        except OnvifError as exc:
            logger.debug("onveef: unsubscribe from %s failed (ignored): %s", url, exc)

    async def set_synchronization_point(self) -> None:
        """Ask the device to re-send the current state of every property it reports."""
        if self.subscription_url:
            await self._client.events_set_synchronization_point(
                subscription_url=self.subscription_url
            )

    async def pull(self) -> list[dict[str, Any]]:
        """Long-poll once and return the notifications received (possibly an empty list)."""
        if not self.subscription_url:
            await self.create()
        if self._auto_renew and time.monotonic() >= self._renew_at:
            try:
                await self.renew()
            except OnvifError as exc:
                logger.debug("onveef: pull-point renew failed, will re-create: %s", exc)
                self.subscription_url = ""
                await self.create()
        try:
            result = await self._client.events_pull_messages(
                subscription_url=self.subscription_url,
                timeout=self._timeout,
                message_limit=self._message_limit,
            )
        except (OnvifFaultError, OnvifOperationNotSupportedError) as exc:
            logger.debug("onveef: pull-point rejected the pull, re-creating: %s", exc)
            self.subscription_url = ""
            await self.create()
            result = await self._client.events_pull_messages(
                subscription_url=self.subscription_url,
                timeout=self._timeout,
                message_limit=self._message_limit,
            )
        messages = result.get("messages")
        return messages if isinstance(messages, list) else []

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        """Yield notifications forever, blocking in the device's long poll between batches."""
        while True:
            for message in await self.pull():
                yield message

    async def __aenter__(self) -> AsyncPullPointSubscription:
        if not self.subscription_url:
            await self.create()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.unsubscribe()
