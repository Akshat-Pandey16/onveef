"""Events operations for the synchronous ONVIF client."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from types import TracebackType
from typing import Any

from onveef import envelopes, parsers
from onveef.exceptions import (
    OnvifError,
    OnvifFaultError,
    OnvifOperationNotSupportedError,
)
from onveef.transport import (
    SyncTransport,
    _iso8601_seconds,
)

logger = logging.getLogger("onveef")


class EventOperations(SyncTransport):
    """Events operations, mixed into :class:`~onveef.client.OnvifClient`."""

    def events_get_event_properties(self) -> dict[str, Any]:
        """Return the ONVIF ``GetEventProperties`` result from the Events service, parsed by ``parsers.parse_event_properties`` into ``dict[str, Any]``."""
        xml = self.call(
            service="events",
            operation="GetEventProperties",
            body_inner=envelopes.events_get_event_properties(),
        )
        return parsers.parse_event_properties(xml)

    def events_create_pull_point(
        self, *, termination_time: str = "PT60S", topic_filter: str = ""
    ) -> dict[str, Any]:
        """Create a pull-point subscription and return its reference and termination times.

        The ``subscription_url`` the device returns is host-rewritten like any other
        device-reported address, so it stays reachable across NAT and port forwards.
        Prefer :meth:`pull_point`, which keeps the subscription alive for you.
        """
        xml = self.call(
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
    ) -> PullPointSubscription:
        """Return a managed pull-point subscription that renews and cleans up after itself.

        A raw pull-point expires at its ``termination_time`` and has to be renewed on a
        clock you maintain. This wrapper renews at half the termination interval, transparently
        re-creates the subscription if the device drops it, and unsubscribes on exit::

            with cam.pull_point(topic_filter="tns1:RuleEngine//.") as sub:
                for message in sub:
                    print(message["topic"], message["data"])

        Iteration blocks in the device's own long poll, so it costs one request per
        ``timeout`` interval rather than a busy loop.
        """
        subscription = PullPointSubscription(
            self,
            termination_time=termination_time,
            topic_filter=topic_filter,
            timeout=timeout,
            message_limit=message_limit,
            auto_renew=auto_renew,
        )
        subscription.create()
        return subscription

    def events_pull_messages(
        self,
        *,
        subscription_url: str,
        timeout: str = "PT5S",
        message_limit: int = 20,
    ) -> dict[str, Any]:
        """Pull queued notifications from a PullPoint ``subscription_url`` and return the parsed messages and termination times as a dict."""
        xml = self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_pull_messages(timeout=timeout, message_limit=message_limit),
            wsa_action=(
                "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
            ),
            operation="PullMessages",
            read_timeout_s=_iso8601_seconds(timeout, 5.0) + 5.0,
        )
        return parsers.parse_pull_messages(xml)

    def events_renew(self, *, subscription_url: str, termination_time: str = "PT60S") -> None:
        """Renew an event subscription's termination time via a WS-BaseNotification ``Renew`` request to ``subscription_url``."""
        self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_renew(termination_time=termination_time),
            wsa_action="http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest",
            operation="Renew",
        )

    def events_unsubscribe(self, *, subscription_url: str) -> None:
        """Cancel an event subscription via a WS-BaseNotification ``Unsubscribe`` request to ``subscription_url``."""
        self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_unsubscribe(),
            wsa_action="http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest",
            operation="Unsubscribe",
        )

    def events_set_synchronization_point(self, *, subscription_url: str) -> None:
        """Request a synchronization point so the device re-emits current property state on the ``subscription_url`` subscription."""
        self._post_subscription(
            subscription_url=subscription_url,
            body=envelopes.events_set_synchronization_point(),
            wsa_action=(
                "http://www.onvif.org/ver10/events/wsdl/"
                "PullPointSubscription/SetSynchronizationPointRequest"
            ),
            operation="SetSynchronizationPoint",
        )

    def events_subscribe(
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
        xml = self.call(
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


class PullPointSubscription:
    """A pull-point subscription that keeps itself alive and tidies up on exit.

    Devices expire a pull-point at its ``TerminationTime`` unless renewed, and each vendor
    reports expiry differently. This wrapper renews at half the termination interval,
    re-creates the subscription when the device has forgotten it, and unsubscribes when the
    ``with`` block ends. Build one with :meth:`OnvifClient.pull_point` rather than directly.
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

    def create(self) -> str:
        """Create (or re-create) the subscription and return its reference URL."""
        result = self._client.events_create_pull_point(
            termination_time=self._termination_time, topic_filter=self._topic_filter
        )
        url = str(result.get("subscription_url") or "")
        if not url:
            raise OnvifFaultError("Device returned a pull-point subscription with no reference.")
        self.subscription_url = url
        self._renew_at = time.monotonic() + self._renew_interval_s
        return url

    def renew(self) -> None:
        """Extend the subscription's termination time."""
        if not self.subscription_url:
            return
        self._client.events_renew(
            subscription_url=self.subscription_url, termination_time=self._termination_time
        )
        self._renew_at = time.monotonic() + self._renew_interval_s

    def unsubscribe(self) -> None:
        """Cancel the subscription, ignoring a device that has already forgotten it."""
        url, self.subscription_url = self.subscription_url, ""
        if not url:
            return
        try:
            self._client.events_unsubscribe(subscription_url=url)
        except OnvifError as exc:
            logger.debug("onveef: unsubscribe from %s failed (ignored): %s", url, exc)

    def set_synchronization_point(self) -> None:
        """Ask the device to re-send the current state of every property it reports."""
        if self.subscription_url:
            self._client.events_set_synchronization_point(subscription_url=self.subscription_url)

    def pull(self) -> list[dict[str, Any]]:
        """Long-poll once and return the notifications received (possibly an empty list)."""
        if not self.subscription_url:
            self.create()
        if self._auto_renew and time.monotonic() >= self._renew_at:
            try:
                self.renew()
            except OnvifError as exc:
                logger.debug("onveef: pull-point renew failed, will re-create: %s", exc)
                self.subscription_url = ""
                self.create()
        try:
            result = self._client.events_pull_messages(
                subscription_url=self.subscription_url,
                timeout=self._timeout,
                message_limit=self._message_limit,
            )
        except (OnvifFaultError, OnvifOperationNotSupportedError) as exc:
            logger.debug("onveef: pull-point rejected the pull, re-creating: %s", exc)
            self.subscription_url = ""
            self.create()
            result = self._client.events_pull_messages(
                subscription_url=self.subscription_url,
                timeout=self._timeout,
                message_limit=self._message_limit,
            )
        messages = result.get("messages")
        return messages if isinstance(messages, list) else []

    def __iter__(self) -> Iterator[dict[str, Any]]:
        """Yield notifications forever, blocking in the device's long poll between batches."""
        while True:
            yield from self.pull()

    def __enter__(self) -> PullPointSubscription:
        if not self.subscription_url:
            self.create()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.unsubscribe()
