"""Shared connection objects and the synchronous transport core.

Everything here is about *reaching* a device — endpoints, credentials, auth,
retries, the circuit breaker and fault classification. The ONVIF operations
themselves live in :mod:`onveef.ops` and are mixed in by
:class:`~onveef.client.OnvifClient`.
"""

from __future__ import annotations

import logging
import random
import re
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from types import TracebackType
from typing import Any, Self

import httpx

from onveef import breaker, envelopes, parsers, urls
from onveef.exceptions import (
    OnvifAuthError,
    OnvifCapabilityMissingError,
    OnvifError,
    OnvifFaultError,
    OnvifNotConfiguredError,
    OnvifOperationNotSupportedError,
    OnvifServiceUnavailableError,
    OnvifTimeoutError,
    OnvifTransportError,
)

logger = logging.getLogger("onveef")


def _package_version() -> str:
    """Return the installed package version, or ``0`` when running from a bare checkout."""
    try:
        return metadata.version("onveef")
    except metadata.PackageNotFoundError:
        return "0"


DEFAULT_TIMEOUT_S = 5.0
DEFAULT_USER_AGENT = f"onveef/{_package_version()}"
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = DEFAULT_MAX_RESPONSE_BYTES
_DEFAULT_DEVICE_PATH = "/onvif/device_service"
_CONTENT_TYPES = (
    "application/soap+xml; charset=utf-8",
    "text/xml; charset=utf-8",
)
_NOAUTH_OPERATIONS = frozenset({"GetSystemDateAndTime", "GetCapabilities", "GetServices"})
_ISO8601_DURATION = re.compile(r"^-?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def _iso8601_seconds(value: str, default: float) -> float:
    """Convert an ISO-8601 duration like ``PT30S`` to seconds; ``default`` if unparseable."""
    match = _ISO8601_DURATION.match(value.strip()) if value else None
    if match is None:
        return default
    days, hours, minutes, seconds = match.groups()
    total = (
        int(days or 0) * 86400
        + int(hours or 0) * 3600
        + int(minutes or 0) * 60
        + float(seconds or 0)
    )
    return total or default


def _is_idempotent(operation: str) -> bool:
    """Whether an operation is safe to retry automatically (reads, not state changes)."""
    return operation.startswith(("Get", "Find", "Pull")) or operation in _NOAUTH_OPERATIONS


@dataclass(slots=True)
class OnvifCredentials:
    """ONVIF account credentials. The password is hidden from ``repr()`` to avoid leaks."""

    username: str = ""
    password: str = field(default="", repr=False)

    @property
    def configured(self) -> bool:
        """``True`` when a username is set (i.e. authenticated calls should be attempted)."""
        return bool(self.username)


@dataclass(slots=True)
class OnvifEndpoint:
    """The device's base URL plus the per-service XAddr map discovered from it."""

    device_xaddr: str
    services: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_host(
        cls,
        host: str,
        *,
        port: int = 80,
        use_https: bool = False,
        device_path: str = _DEFAULT_DEVICE_PATH,
    ) -> OnvifEndpoint:
        """Build an endpoint for ``host``/``port``, deriving the device-service URL.

        Bare hosts, ``host:port`` strings, and full ``http(s)://`` URLs are all accepted.
        """
        if "://" in host:
            device_xaddr = host
        else:
            scheme = "https" if use_https else "http"
            netloc = host if ":" in host else f"{host}:{port}"
            device_xaddr = f"{scheme}://{netloc}{device_path}"
        return cls(device_xaddr=device_xaddr)

    def url(self, key: str) -> str:
        """Return the XAddr for a service key (``""`` if not advertised)."""
        if key == "device":
            return self.services.get("device") or self.device_xaddr
        return self.services.get(key, "")

    def has(self, key: str) -> bool:
        """Whether the device advertises the given service key."""
        return bool(self.services.get(key))


@dataclass(slots=True)
class OnvifCallResult:
    xml: str
    operation: str
    xaddr: str


class SyncTransport:
    """The transport half of :class:`~onveef.client.OnvifClient`.

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
        transport: httpx.BaseTransport | None = None,
        proxy: str | None = None,
        http_client: httpx.Client | None = None,
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
        self._clock_offset_s = 0.0
        self._clock_synced = False
        self._clock_syncing = False
        self._discover_lock = threading.RLock()
        self._clock_lock = threading.RLock()
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self._timeout,
            verify=verify_tls,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            transport=transport,
            proxy=proxy,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool, unless it was supplied by the caller."""
        if self._owns_client:
            self._client.close()

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

    def connect(self) -> Self:
        """Eagerly discover the device's services and return ``self`` for chaining.

        Optional — services are discovered lazily on first use anyway — but handy when you
        want discovery (and any auth/connectivity failure) to happen up front.
        """
        self._discover_once()
        return self

    def get_capabilities(self) -> dict[str, str]:
        """Return the ONVIF ``GetCapabilities`` result from the Device service, parsed by ``parsers.parse_capabilities`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetCapabilities",
            body_inner=envelopes.device_get_capabilities(),
        )
        return parsers.parse_capabilities(xml)

    def get_services(self) -> dict[str, str]:
        """Return the ONVIF ``GetServices`` result from the Device service, parsed by ``parsers.parse_services`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetServices",
            body_inner=envelopes.device_get_services(include_capability=False),
        )
        return parsers.parse_services(xml)

    def discover_services(self) -> dict[str, str]:
        """Return the device's service-to-XAddr map, trying ``GetServices`` first and falling back to ``GetCapabilities``.

        Unless ``rewrite_host=False`` was passed, every XAddr is re-pointed at the address
        this client reached the device on, so devices that advertise their own unreachable
        address (NAT, port forward, Docker bridge, stale DHCP lease) still work.
        """
        try:
            services = self.get_services()
            if not services:
                services = self.get_capabilities()
        except OnvifFaultError:
            services = self.get_capabilities()
        if not self._rewrite_host:
            return services
        return urls.rewrite_service_map(services, self._endpoint.device_xaddr)

    def get_system_date_time(self) -> dict[str, Any]:
        """Return the ONVIF ``GetSystemDateAndTime`` result from the Device service, parsed by ``parsers.parse_system_datetime`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetSystemDateAndTime",
            body_inner=envelopes.device_get_system_date_time(),
        )
        return parsers.parse_system_datetime(xml)

    def _discover_once(self) -> None:
        if self._discovered:
            return
        with self._discover_lock:
            if self._discovered:
                return
            try:
                services = self.discover_services()
            except OnvifError:
                services = {}
            finally:
                self._discovered = True
            if services:
                merged = {**services, **{k: v for k, v in self._endpoint.services.items() if v}}
                self._endpoint = OnvifEndpoint(self._endpoint.device_xaddr, services=merged)

    def _has(self, service: str) -> bool:
        """Whether the device advertises ``service``, running auto-discovery first if needed."""
        if not self._endpoint.has(service) and self._auto_discover and not self._discovered:
            self._discover_once()
        return self._endpoint.has(service)

    def require(self, service: str) -> str:
        """Resolve a service key to its XAddr, discovering services first if needed.

        Raises:
            OnvifCapabilityMissingError: if the device does not advertise the service.
        """
        url = self._endpoint.url(service)
        if url:
            return url
        if service != "device" and self._auto_discover and not self._discovered:
            self._discover_once()
            url = self._endpoint.url(service)
            if url:
                return url
        raise OnvifCapabilityMissingError(
            f"Device does not advertise the '{service}' ONVIF service."
        )

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

    def _raw_post(
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
            else httpx.Timeout(self._timeout, read=read_timeout_s)
        )
        with self._client.stream(
            "POST",
            url,
            content=envelope,
            headers={"Content-Type": content_type},
            timeout=timeout,
            auth=auth,
        ) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
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

    def _post_soap(
        self,
        *,
        url: str,
        envelope: str,
        content_type: str,
        read_timeout_s: float | None = None,
    ) -> tuple[int, str]:
        status, text, challenge = self._raw_post(
            url=url,
            content_type=content_type,
            envelope=envelope,
            auth=None,
            read_timeout_s=read_timeout_s,
        )
        if status == 401:
            auth = self._http_auth_for(challenge)
            if auth is not None:
                status, text, _ = self._raw_post(
                    url=url,
                    content_type=content_type,
                    envelope=envelope,
                    auth=auth,
                    read_timeout_s=read_timeout_s,
                )
        return status, text

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + random.random()
        return float(min(2.0, 0.25 * (2**attempt)) * jitter)

    def _send_cycle(
        self, *, xaddr: str, operation: str, envelope: str, read_timeout_s: float | None = None
    ) -> str:
        last_status = 0
        last_text = ""
        for ct in _CONTENT_TYPES:
            try:
                status, text = self._post_soap(
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
                fault = parsers.parse_fault(text)
                if "NotAuthorized" in fault or "Sender not Authorized" in fault:
                    raise OnvifAuthError(f"ONVIF call '{operation}' denied: {fault}")
                if parsers.fault_is_unsupported(fault):
                    raise OnvifOperationNotSupportedError(
                        f"ONVIF call '{operation}' is not supported by this device."
                    )
                raise OnvifFaultError(f"ONVIF call '{operation}' fault: {fault}")
            self._record_success()
            return text
        self._record_failure()
        if last_status == 0:
            raise OnvifTransportError(f"ONVIF call '{operation}' transport failed.")
        raise OnvifTransportError(
            f"ONVIF call '{operation}' returned HTTP {last_status}: {last_text[:200]}"
        )

    def _call_raw(
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
                return self._send_cycle(
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
                time.sleep(self._backoff(attempt))
        assert transient is not None
        raise transient

    def call(
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
        Most callers should use the typed helper methods instead.

        Args:
            service: Service key (``"device"``, ``"media"``, ``"ptz"``, …).
            operation: ONVIF operation name (for logging and idempotency detection).
            body_inner: The SOAP ``Body`` inner XML (see :mod:`onveef.envelopes`).
            require_auth: Force auth on/off; ``None`` decides automatically.
            read_timeout_s: Override the read timeout for this one request (used by
                long-polling operations). Retries are disabled when it is set, and the
                override never leaks into other requests sharing this client.
        """
        xaddr = self.require(service)
        wants_auth = self._credentials.configured
        if require_auth is False:
            wants_auth = False
        elif require_auth is True:
            wants_auth = True
        elif operation in _NOAUTH_OPERATIONS:
            wants_auth = self._credentials.configured
        if not wants_auth:
            try:
                return self._call_raw(
                    xaddr=xaddr,
                    operation=operation,
                    body_inner=body_inner,
                    with_auth=False,
                    read_timeout_s=read_timeout_s,
                )
            except OnvifAuthError:
                if not self._credentials.configured:
                    raise
        try:
            return self._call_raw(
                xaddr=xaddr,
                operation=operation,
                body_inner=body_inner,
                with_auth=True,
                read_timeout_s=read_timeout_s,
            )
        except OnvifAuthError:
            if not self._credentials.configured:
                raise
            if not self._clock_synced:
                self._sync_clock_offset()
                if self._clock_offset_s != 0.0:
                    try:
                        return self._call_raw(
                            xaddr=xaddr,
                            operation=operation,
                            body_inner=body_inner,
                            with_auth=True,
                            read_timeout_s=read_timeout_s,
                        )
                    except OnvifAuthError:
                        pass
            if self._password_text_fallback and not self._password_text:
                logger.warning(
                    "onveef: digest auth failed for '%s'; retrying with plaintext PasswordText%s",
                    operation,
                    " over an unencrypted http:// connection"
                    if xaddr.startswith("http://")
                    else "",
                )
                return self._call_raw(
                    xaddr=xaddr,
                    operation=operation,
                    body_inner=body_inner,
                    with_auth=True,
                    password_text=True,
                    read_timeout_s=read_timeout_s,
                )
            raise

    def _sync_clock_offset(self) -> None:
        if self._clock_synced or self._clock_syncing:
            return
        with self._clock_lock:
            if self._clock_synced or self._clock_syncing:
                return
            self._clock_syncing = True
            try:
                info = self.get_system_date_time()
            except (
                OnvifAuthError,
                OnvifFaultError,
                OnvifTransportError,
                OnvifCapabilityMissingError,
            ):
                return
            finally:
                self._clock_syncing = False
            utc = info.get("UTCDateTime")
            if not isinstance(utc, dict):
                return
            try:
                device_utc = datetime(
                    utc["year"],
                    utc["month"],
                    utc["day"],
                    utc["hour"],
                    utc["minute"],
                    utc["second"],
                    tzinfo=UTC,
                )
            except (KeyError, ValueError, TypeError):
                return
            self._clock_offset_s = (device_utc - datetime.now(UTC)).total_seconds()
            self._clock_synced = True

    def _media_service(self) -> tuple[str, bool]:
        if self._has("media"):
            return "media", False
        if self._has("media2"):
            return "media2", True
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    def _relay_service(self) -> tuple[str, bool]:
        if self._has("deviceio"):
            return "deviceio", True
        return "device", False

    def _post_subscription(
        self,
        *,
        subscription_url: str,
        body: str,
        wsa_action: str,
        operation: str,
        read_timeout_s: float | None = None,
    ) -> str:
        def build() -> str:
            return envelopes.build_envelope(
                body,
                username=self._credentials.username,
                password=self._credentials.password,
                wsa_action=wsa_action,
                wsa_to=subscription_url,
                clock_offset_s=self._clock_offset_s,
                use_password_text=self._password_text,
                add_timestamp=self._ws_timestamp,
            )

        try:
            return self._post_xml(
                url=subscription_url,
                envelope=build(),
                operation=operation,
                read_timeout_s=read_timeout_s,
            )
        except OnvifAuthError:
            if self._clock_synced or not self._credentials.configured:
                raise
            self._sync_clock_offset()
            if self._clock_offset_s == 0.0:
                raise
            return self._post_xml(
                url=subscription_url,
                envelope=build(),
                operation=operation,
                read_timeout_s=read_timeout_s,
            )

    def _post_xml(
        self, *, url: str, envelope: str, operation: str, read_timeout_s: float | None = None
    ) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        return self._send_cycle(
            xaddr=url, operation=operation, envelope=envelope, read_timeout_s=read_timeout_s
        )

    def _require_media1(self, operation: str) -> None:
        if not self._has("media"):
            raise OnvifCapabilityMissingError(f"{operation} requires the legacy Media service.")


def _snapshot_get(
    *,
    snapshot_uri: str,
    auth: httpx.Auth | None,
    timeout_s: float,
    verify_tls: bool | str | ssl.SSLContext,
) -> tuple[int, bytes, str]:
    try:
        with (
            httpx.Client(
                timeout=timeout_s, verify=verify_tls, auth=auth, follow_redirects=False
            ) as client,
            client.stream(
                "GET", snapshot_uri, headers={"User-Agent": DEFAULT_USER_AGENT}
            ) as response,
        ):
            if response.status_code >= 400:
                return response.status_code, b"", ""
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise OnvifTransportError(
                        f"Snapshot exceeded the {_MAX_RESPONSE_BYTES}-byte cap."
                    )
            return (
                response.status_code,
                bytes(body),
                response.headers.get("Content-Type", "image/jpeg"),
            )
    except httpx.HTTPError as exc:
        raise OnvifTransportError(f"Snapshot fetch failed: {exc}") from exc


def fetch_snapshot_bytes(
    *,
    snapshot_uri: str,
    credentials: OnvifCredentials,
    timeout_s: float = 8.0,
    verify_tls: bool | str | ssl.SSLContext = True,
) -> tuple[bytes, str]:
    """Fetch a JPEG snapshot from a snapshot URI using HTTP Digest (then Basic) auth.

    Args:
        snapshot_uri: The URI returned by ``GetSnapshotUri``.
        credentials: Account used for HTTP auth (anonymous if not configured).
        timeout_s: Per-request timeout.
        verify_tls: Verify TLS certs (default ``True``; pass ``False`` for self-signed).

    Returns:
        ``(image_bytes, content_type)``.
    """
    if not snapshot_uri:
        raise OnvifCapabilityMissingError("Snapshot URI is not available.")
    auth: httpx.Auth | None = (
        httpx.DigestAuth(credentials.username, credentials.password)
        if credentials.configured
        else None
    )
    status, body, content_type = _snapshot_get(
        snapshot_uri=snapshot_uri, auth=auth, timeout_s=timeout_s, verify_tls=verify_tls
    )
    if status == 401 and credentials.configured:
        status, body, content_type = _snapshot_get(
            snapshot_uri=snapshot_uri,
            auth=httpx.BasicAuth(credentials.username, credentials.password),
            timeout_s=timeout_s,
            verify_tls=verify_tls,
        )
    if status == 401:
        raise OnvifAuthError("Snapshot request was unauthorized.")
    if status >= 400:
        raise OnvifTransportError(f"Snapshot returned HTTP {status}.")
    return body, content_type
