"""Shared connection objects and the asyncio transport core.

Everything here is about *reaching* a device — endpoints, credentials, auth,
retries, the circuit breaker and fault classification. The ONVIF operations
themselves live in :mod:`onveef.aops` and are mixed in by
:class:`~onveef.aclient.AsyncOnvifClient`.
"""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, TypeVar

import httpx

from onveef import breaker, envelopes, parsers, urls
from onveef.exceptions import (
    OnvifAuthError,
    OnvifCapabilityMissingError,
    OnvifError,
    OnvifFaultError,
    OnvifNotConfiguredError,
    OnvifServiceUnavailableError,
    OnvifTimeoutError,
    OnvifTransportError,
)
from onveef.transport import (
    _CLOCK_RESYNC_INTERVAL_S,
    _CLOCK_RESYNC_MIN_S,
    _CONTENT_TYPES,
    _DEFAULT_DEVICE_PATH,
    _LONG_POLL_GRACE_S,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    ClockResyncCallback,
    OnvifCredentials,
    OnvifEndpoint,
    _device_utc,
    _fault_error,
    _is_idempotent,
)

logger = logging.getLogger("onveef")

UTC = timezone.utc  # the object datetime.UTC names on Python 3.11+
_AsyncT = TypeVar("_AsyncT", bound="AsyncTransport")  # typing.Self is Python 3.11+


class AsyncTransport:
    """The transport half of :class:`~onveef.aclient.AsyncOnvifClient`.

    Holds the endpoint, credentials and HTTP client, and turns a service key plus a
    SOAP body into a response string — auth, clock-skew recovery, content-type
    negotiation, retries, the circuit breaker and fault classification included.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = 80,
        username: str = "",
        password: str = "",
        *,
        use_https: bool = False,
        device_path: str = _DEFAULT_DEVICE_PATH,
        endpoint: OnvifEndpoint | None = None,
        credentials: OnvifCredentials | None = None,
        auto_discover: bool | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        verify_tls: bool | str | ssl.SSLContext = True,
        rewrite_host: bool = True,
        breaker_key: str | None = None,
        breaker_window_s: float = 60.0,
        breaker_threshold: int = 3,
        breaker_open_s: float = 30.0,
        password_text: bool = False,
        password_text_fallback: bool = False,
        ws_timestamp: bool = False,
        http_auth: str = "auto",
        retries: int = 2,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.AsyncBaseTransport | None = None,
        proxy: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock_offset_s: float = 0.0,
        on_clock_resync: ClockResyncCallback | None = None,
    ) -> None:
        if endpoint is None:
            if not host:
                raise OnvifNotConfiguredError(
                    "Provide host=... (e.g. '192.168.1.64') or a pre-built endpoint=..."
                )
            endpoint = OnvifEndpoint.for_host(
                host, port=port, use_https=use_https, device_path=device_path
            )
            auto_discover = True if auto_discover is None else auto_discover
        else:
            auto_discover = False if auto_discover is None else auto_discover
        if credentials is None:
            credentials = OnvifCredentials(username, password)

        self._endpoint = endpoint
        self._credentials = credentials
        self._timeout_s = timeout_s
        self._timeout = httpx.Timeout(
            timeout_s,
            connect=connect_timeout_s if connect_timeout_s is not None else timeout_s,
            read=read_timeout_s if read_timeout_s is not None else timeout_s,
        )
        self._verify_tls = verify_tls
        self._http_auth = http_auth
        self._retries = max(0, retries)
        self._max_response_bytes = max_response_bytes
        self._breaker_key = breaker_key
        self._breaker = (
            breaker.CircuitBreaker(
                window_s=breaker_window_s, threshold=breaker_threshold, open_s=breaker_open_s
            )
            if breaker_key is not None
            else None
        )
        self._password_text = password_text
        self._password_text_fallback = password_text_fallback
        self._ws_timestamp = ws_timestamp
        self._auto_discover = auto_discover
        self._rewrite_host = rewrite_host
        self._discovered = False
        self._clock_offset_s = float(clock_offset_s)
        self._on_clock_resync = on_clock_resync
        self._clock_checked_at = float("-inf")
        self._clock_sync_task: asyncio.Task[Any] | None = None
        self._sticky_http_auth: httpx.Auth | None = None
        self._clock_lock = asyncio.Lock()
        self._discover_lock = asyncio.Lock()
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=self._timeout,
            verify=verify_tls,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            transport=transport,
            proxy=proxy,
        )

    async def __aenter__(self: _AsyncT) -> _AsyncT:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async pool, unless the client was supplied by the caller."""
        if self._owns_client:
            await self._client.aclose()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(device_xaddr={self._endpoint.device_xaddr!r}, "
            f"username={self._credentials.username!r}, "
            f"services={sorted(self._endpoint.services)})"
        )

    def local_address(self) -> str:
        """Return the host this client connects to, used as the host-rewrite reference."""
        return urls.host_of(self._endpoint.device_xaddr)

    def _fix_url(self, url: str) -> str:
        """Re-point a device-reported URL at the address we reached the device on."""
        if not self._rewrite_host:
            return url
        return urls.rewrite_host(url, self._endpoint.device_xaddr)

    @property
    def endpoint(self) -> OnvifEndpoint:
        """The current endpoint (base URL + discovered service map)."""
        return self._endpoint

    def set_endpoint(self, endpoint: OnvifEndpoint) -> None:
        """Replace the endpoint (e.g. after discovering services yourself)."""
        self._endpoint = endpoint

    @property
    def credentials(self) -> OnvifCredentials:
        """The credentials this client authenticates with."""
        return self._credentials

    @property
    def clock_offset_s(self) -> float:
        """Seconds the device's clock is ahead of this host's (negative when behind).

        See :attr:`onveef.client.OnvifClient.clock_offset_s`.
        """
        return self._clock_offset_s

    async def connect(self: _AsyncT) -> _AsyncT:
        """Eagerly discover the device's services and return ``self`` for chaining."""
        await self._discover_once()
        return self

    async def get_capabilities(self) -> dict[str, str]:
        """Return the device's advertised capability service URLs."""
        xml = await self.call(
            service="device",
            operation="GetCapabilities",
            body_inner=envelopes.device_get_capabilities(),
        )
        return parsers.parse_capabilities(xml)

    async def get_services(self) -> dict[str, str]:
        """Return the device's per-service XAddr map from ``GetServices``."""
        xml = await self.call(
            service="device",
            operation="GetServices",
            body_inner=envelopes.device_get_services(include_capability=False),
        )
        return parsers.parse_services(xml)

    async def discover_services(self) -> dict[str, str]:
        """Discover per-service XAddrs, preferring ``GetServices`` and falling back to caps.

        Unless ``rewrite_host=False`` was passed, every XAddr is re-pointed at the address
        this client reached the device on, so devices that advertise their own unreachable
        address (NAT, port forward, Docker bridge, stale DHCP lease) still work.
        """
        try:
            services = await self.get_services()
            if not services:
                services = await self.get_capabilities()
        except OnvifFaultError:
            services = await self.get_capabilities()
        if not self._rewrite_host:
            return services
        return urls.rewrite_service_map(services, self._endpoint.device_xaddr)

    async def get_system_date_time(self) -> dict[str, Any]:
        """Return the device's system date/time (UTC and local).

        Sent without WS-Security first, like :meth:`onveef.client.OnvifClient.get_system_date_time`.
        """
        xml = await self.call(
            service="device",
            operation="GetSystemDateAndTime",
            body_inner=envelopes.device_get_system_date_time(),
            require_auth=False,
        )
        return parsers.parse_system_datetime(xml)

    async def _discover_once(self) -> None:
        if self._discovered:
            return
        async with self._discover_lock:
            if self._discovered:
                return
            try:
                services = await self.discover_services()
            except OnvifError:
                services = {}
            finally:
                self._discovered = True
            if services:
                merged = {**services, **{k: v for k, v in self._endpoint.services.items() if v}}
                self._endpoint = OnvifEndpoint(self._endpoint.device_xaddr, services=merged)

    async def _has(self, service: str) -> bool:
        """Whether the device advertises ``service``, running auto-discovery first if needed."""
        if not self._endpoint.has(service) and self._auto_discover and not self._discovered:
            await self._discover_once()
        return self._endpoint.has(service)

    async def _ensure(self, service: str) -> None:
        """Run auto-discovery if ``service`` (other than ``device``) is not yet resolved."""
        if (
            service != "device"
            and not self._endpoint.has(service)
            and self._auto_discover
            and not self._discovered
        ):
            await self._discover_once()

    def require(self, service: str) -> str:
        """Resolve a service key to its XAddr (discovery must already have run for it).

        Raises:
            OnvifCapabilityMissingError: if the device does not advertise the service.
        """
        url = self._endpoint.url(service)
        if url:
            return url
        raise OnvifCapabilityMissingError(
            f"Device does not advertise the '{service}' ONVIF service."
        )

    async def _media_service(self) -> tuple[str, bool]:
        """Return the preferred media service key and whether it is Media2."""
        if await self._has("media"):
            return "media", False
        if await self._has("media2"):
            return "media2", True
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    async def _relay_service(self) -> tuple[str, bool]:
        """Return the relay-capable service key and whether it is the DeviceIO service."""
        if await self._has("deviceio"):
            return "deviceio", True
        return "device", False

    async def _require_media1(self, operation: str) -> None:
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(f"{operation} requires the legacy Media service.")

    def _record_failure(self) -> None:
        if self._breaker is not None and self._breaker_key is not None:
            self._breaker.record_failure(self._breaker_key)

    def _record_success(self) -> None:
        if self._breaker is not None and self._breaker_key is not None:
            self._breaker.record_success(self._breaker_key)

    def _breaker_open(self) -> bool:
        return (
            self._breaker is not None
            and self._breaker_key is not None
            and self._breaker.is_open(self._breaker_key)
        )

    def _http_auth_for(self, challenge: str) -> httpx.Auth | None:
        if self._http_auth == "none" or not self._credentials.configured:
            return None
        want = self._http_auth
        if want == "auto":
            want = "digest" if "digest" in challenge.lower() else "basic"
        if want == "digest":
            return httpx.DigestAuth(self._credentials.username, self._credentials.password)
        if want == "basic":
            return httpx.BasicAuth(self._credentials.username, self._credentials.password)
        return None

    async def _raw_post(
        self,
        *,
        url: str,
        content_type: str,
        envelope: str,
        auth: httpx.Auth | None,
        read_timeout_s: float | None,
    ) -> tuple[int, str, str]:
        timeout = (
            self._timeout
            if read_timeout_s is None
            else httpx.Timeout(
                connect=self._timeout.connect,
                read=read_timeout_s,
                write=self._timeout.write,
                pool=self._timeout.pool,
            )
        )
        async with self._client.stream(
            "POST",
            url,
            content=envelope,
            headers={"Content-Type": content_type},
            timeout=timeout,
            auth=auth,
        ) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > self._max_response_bytes:
                    raise OnvifTransportError(
                        f"ONVIF response exceeded the {self._max_response_bytes}-byte cap."
                    )
            encoding = response.encoding or "utf-8"
            try:
                text = bytes(body).decode(encoding, errors="replace")
            except LookupError:
                text = bytes(body).decode("utf-8", errors="replace")
            return response.status_code, text, response.headers.get("WWW-Authenticate", "")

    async def _post_soap(
        self,
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        auth = self._sticky_http_auth
        status, text, challenge = await self._raw_post(
            url=url,
            content_type=content_type,
            envelope=envelope,
            auth=auth,
            read_timeout_s=read_timeout_s,
        )
        if status == 401 and auth is None:
            auth = self._http_auth_for(challenge)
            if auth is not None:
                status, text, _ = await self._raw_post(
                    url=url,
                    content_type=content_type,
                    envelope=envelope,
                    auth=auth,
                    read_timeout_s=read_timeout_s,
                )
                if status != 401:
                    # Answer the device's HTTP auth up front from now on (see the sync client).
                    self._sticky_http_auth = auth
        return status, text

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + random.random()
        return float(min(2.0, 0.25 * (2**attempt)) * jitter)

    async def _send_cycle(
        self, *, xaddr: str, operation: str, envelope: str, read_timeout_s: float | None = None
    ) -> str:
        last_status = 0
        last_text = ""
        for ct in _CONTENT_TYPES:
            try:
                status, text = await self._post_soap(
                    url=xaddr,
                    envelope=envelope,
                    content_type=ct,
                    read_timeout_s=read_timeout_s,
                )
            except httpx.TimeoutException as exc:
                if read_timeout_s is None:
                    self._record_failure()
                raise OnvifTimeoutError(f"ONVIF call '{operation}' timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                self._record_failure()
                raise OnvifTransportError(f"ONVIF transport error: {exc}", retryable=True) from exc
            except OnvifTransportError:
                self._record_failure()
                raise
            last_status, last_text = status, text
            if status in (400, 415) and not parsers.has_soap_fault(text):
                continue
            if 300 <= status < 400:
                self._record_failure()
                raise OnvifTransportError(
                    f"ONVIF call '{operation}' was redirected (HTTP {status}); "
                    "point the endpoint at the final URL (e.g. https)."
                )
            if status == 401:
                raise OnvifAuthError(f"ONVIF call '{operation}' was unauthorized.")
            if status == 503:
                self._record_failure()
                raise OnvifServiceUnavailableError(
                    f"ONVIF call '{operation}' unavailable (HTTP 503)."
                )
            if status >= 500 and not parsers.has_soap_fault(text):
                self._record_failure()
                raise OnvifTransportError(
                    f"ONVIF call '{operation}' returned HTTP {status}.", retryable=True
                )
            if parsers.has_soap_fault(text):
                raise _fault_error(operation, text)
            self._record_success()
            return text
        self._record_failure()
        if last_status == 0:
            raise OnvifTransportError(f"ONVIF call '{operation}' transport failed.")
        raise OnvifTransportError(
            f"ONVIF call '{operation}' returned HTTP {last_status}: {last_text[:200]}"
        )

    async def _call_raw(
        self,
        *,
        xaddr: str,
        operation: str,
        body_inner: str,
        with_auth: bool,
        password_text: bool | None = None,
        read_timeout_s: float | None = None,
    ) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        text_mode = self._password_text if password_text is None else password_text
        long_poll = read_timeout_s is not None
        max_attempts = 1 if long_poll or not _is_idempotent(operation) else self._retries + 1
        transient: OnvifError | None = None
        for attempt in range(max_attempts):
            envelope = envelopes.build_envelope(
                body_inner,
                username=self._credentials.username if with_auth else "",
                password=self._credentials.password if with_auth else "",
                clock_offset_s=self._clock_offset_s if with_auth else 0.0,
                use_password_text=text_mode if with_auth else False,
                add_timestamp=self._ws_timestamp if with_auth else False,
            )
            try:
                return await self._send_cycle(
                    xaddr=xaddr,
                    operation=operation,
                    envelope=envelope,
                    read_timeout_s=read_timeout_s,
                )
            except (OnvifTimeoutError, OnvifServiceUnavailableError) as exc:
                transient = exc
            except OnvifTransportError as exc:
                if not exc.retryable:
                    raise
                transient = exc
            if attempt + 1 < max_attempts:
                logger.debug(
                    "onveef: retrying '%s' after transient error (attempt %d/%d)",
                    operation,
                    attempt + 2,
                    max_attempts,
                )
                await asyncio.sleep(self._backoff(attempt))
        assert transient is not None
        raise transient

    async def call(
        self,
        *,
        service: str,
        operation: str,
        body_inner: str,
        require_auth: bool | None = None,
        read_timeout_s: float | None = None,
    ) -> str:
        """Send one SOAP operation and return the raw response XML (advanced/escape hatch).

        Handles auth (WS-Security digest, clock-skew resync, optional plaintext fallback),
        content-type negotiation, retries, the circuit breaker, and fault classification.
        ``read_timeout_s`` overrides the read timeout for this one request without leaking
        into other requests that share this client.
        """
        await self._ensure(service)
        xaddr = self.require(service)
        wants_auth = self._credentials.configured if require_auth is None else require_auth
        if not wants_auth:
            try:
                return await self._call_raw(
                    xaddr=xaddr,
                    operation=operation,
                    body_inner=body_inner,
                    with_auth=False,
                    read_timeout_s=read_timeout_s,
                )
            except OnvifAuthError:
                if not self._credentials.configured:
                    raise
        return await self._with_auth_recovery(
            lambda password_text: self._call_raw(
                xaddr=xaddr,
                operation=operation,
                body_inner=body_inner,
                with_auth=True,
                password_text=password_text,
                read_timeout_s=read_timeout_s,
            ),
            operation=operation,
            url=xaddr,
        )

    async def _with_auth_recovery(
        self,
        send: Callable[[bool | None], Awaitable[str]],
        *,
        operation: str,
        url: str,
    ) -> str:
        """Run an authenticated ``send`` and recover from wrongly refused logins.

        See :meth:`onveef.transport.SyncTransport._with_auth_recovery`.
        """
        used_offset, used_text = self._clock_offset_s, self._password_text
        try:
            return await send(None)
        except OnvifAuthError:
            if not self._credentials.configured:
                raise
            if await self._resync_clock(used_offset) or self._password_text != used_text:
                try:
                    return await send(None)
                except OnvifAuthError:
                    pass
            if self._password_text or not self._password_text_fallback:
                raise
        logger.warning(
            "onveef: digest auth failed for '%s'; retrying with plaintext PasswordText%s",
            operation,
            " over an unencrypted http:// connection" if url.startswith("http://") else "",
        )
        result = await send(True)
        if not self._password_text:
            self._password_text = True
            logger.warning(
                "onveef: %s accepted PasswordText; this client uses it from now on",
                self._endpoint.device_xaddr,
            )
        return result

    async def _resync_clock(self, used_offset: float) -> bool:
        """Re-measure the device clock after a refused login; ``True`` when a retry is worth it.

        See :meth:`onveef.transport.SyncTransport._resync_clock`. ``asyncio.Lock`` is not
        reentrant, so a refusal of the clock read itself — which re-enters this from the
        task holding the lock — is recognised by task and answered ``False``.
        """
        if self._clock_sync_task is not None and self._clock_sync_task is asyncio.current_task():
            return False
        async with self._clock_lock:
            if abs(self._clock_offset_s - used_offset) >= _CLOCK_RESYNC_MIN_S:
                return True
            now = time.monotonic()
            if now - self._clock_checked_at < _CLOCK_RESYNC_INTERVAL_S:
                return False
            self._clock_checked_at = now
            self._clock_sync_task = asyncio.current_task()
            try:
                device_utc = _device_utc(await self.get_system_date_time())
            except OnvifError:
                return False
            finally:
                self._clock_sync_task = None
            if device_utc is None:
                return False
            offset = (device_utc - datetime.now(UTC)).total_seconds()
            self._clock_offset_s = offset
        logger.debug("onveef: %s clock offset is %.1fs", self._endpoint.device_xaddr, offset)
        if self._on_clock_resync is not None:
            self._on_clock_resync(offset)
        return abs(offset - used_offset) >= _CLOCK_RESYNC_MIN_S

    def _use_password(self, password: str) -> None:
        """Authenticate with ``password`` from now on (after changing it on the device)."""
        self._credentials = OnvifCredentials(self._credentials.username, password)
        self._sticky_http_auth = None

    def _long_poll_timeout(self, held_s: float) -> float:
        """The read timeout for a request the device may legitimately hold for ``held_s``."""
        read = self._timeout.read
        return max(read if read is not None else 0.0, held_s + _LONG_POLL_GRACE_S)

    async def _post_xml(
        self, *, url: str, envelope: str, operation: str, read_timeout_s: float | None = None
    ) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        return await self._send_cycle(
            xaddr=url, operation=operation, envelope=envelope, read_timeout_s=read_timeout_s
        )

    async def _post_subscription(
        self,
        *,
        subscription_url: str,
        body: str,
        wsa_action: str,
        operation: str,
        read_timeout_s: float | None = None,
    ) -> str:
        async def send(password_text: bool | None) -> str:
            envelope = envelopes.build_envelope(
                body,
                username=self._credentials.username,
                password=self._credentials.password,
                wsa_action=wsa_action,
                wsa_to=subscription_url,
                clock_offset_s=self._clock_offset_s,
                use_password_text=self._password_text if password_text is None else password_text,
                add_timestamp=self._ws_timestamp,
            )
            return await self._post_xml(
                url=subscription_url,
                envelope=envelope,
                operation=operation,
                read_timeout_s=read_timeout_s,
            )

        return await self._with_auth_recovery(send, operation=operation, url=subscription_url)
