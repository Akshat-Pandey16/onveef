"""High-level synchronous ONVIF client and its device-operation wrappers."""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from onveef import breaker, envelopes, pacs, parsers
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

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_USER_AGENT = "onveef/0.4"
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


class OnvifClient:
    """A synchronous ONVIF client for a single device.

    The quick way to connect is just host/port/username/password — service endpoints are
    discovered automatically on first use::

        with OnvifClient("192.168.1.64", 80, "admin", "secret") as cam:
            print(cam.get_device_information())
            for profile in cam.get_profiles():
                print(cam.get_stream_uri(profile_token=profile["token"]))

    For full control you may instead pass a pre-built ``endpoint=`` (and ``credentials=``);
    in that mode auto-discovery is off by default and you manage the service map yourself.

    Args:
        host: Device IP/hostname, ``host:port``, or a full ``http(s)://.../device_service``
            URL. Omit only when passing ``endpoint=``.
        port: Device port (ignored if ``host`` already includes one or is a full URL).
        username: ONVIF account user (empty means anonymous — only unauthenticated calls).
        password: ONVIF account password.
        use_https: Build an ``https://`` device URL from ``host``/``port``.
        device_path: Path of the device management service (default ``/onvif/device_service``).
        endpoint: Pre-built endpoint (alternative to ``host``); disables auto-discovery
            unless ``auto_discover=True`` is also passed.
        credentials: Pre-built credentials (alternative to ``username``/``password``).
        auto_discover: Discover per-service endpoints lazily on first use. Defaults to
            ``True`` for the host form and ``False`` for the ``endpoint=`` form.
        timeout_s: Default timeout applied to connect/read/write/pool.
        connect_timeout_s / read_timeout_s: Override individual phases (e.g. a longer read).
        verify_tls: Verify TLS certificates. Set ``False`` for cameras with self-signed certs.
        breaker_key: Enable a per-client circuit breaker keyed by this id. Omit to disable.
        breaker_window_s / breaker_threshold / breaker_open_s: Circuit-breaker tuning.
        password_text: Always send the WS-Security password as plaintext ``PasswordText``.
        password_text_fallback: On a digest ``401``, retry once with ``PasswordText`` (some
            cheap firmware only accepts plaintext). A warning is logged when this triggers,
            and it is **plaintext over the wire** on non-HTTPS transports.
        ws_timestamp: Add a ``<wsu:Timestamp>`` to the security header (some strict devices).
        http_auth: HTTP transport auth to try when a device answers ``401`` with a
            ``WWW-Authenticate`` challenge — ``"auto"`` (Digest then Basic), ``"digest"``,
            ``"basic"``, or ``"none"``.
        retries: Automatic retries for transient failures on idempotent (read) operations.
        max_response_bytes: Hard cap on a single SOAP response body.
        user_agent: HTTP ``User-Agent`` header.
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
        verify_tls: bool = True,
        breaker_key: str | None = None,
        breaker_window_s: float = 60.0,
        breaker_threshold: int = 3,
        breaker_open_s: float = 30.0,
        password_text: bool = False,
        password_text_fallback: bool = True,
        ws_timestamp: bool = False,
        http_auth: str = "auto",
        retries: int = 2,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
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
        self._discovered = False
        self._clock_offset_s = 0.0
        self._clock_synced = False
        self._clock_syncing = False
        self._read_override_s: float | None = None
        self._client = httpx.Client(
            timeout=self._timeout,
            verify=verify_tls,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )

    def __enter__(self) -> OnvifClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

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

    def connect(self) -> OnvifClient:
        """Eagerly discover the device's services and return ``self`` for chaining.

        Optional — services are discovered lazily on first use anyway — but handy when you
        want discovery (and any auth/connectivity failure) to happen up front.
        """
        self._discover_once()
        return self

    def _discover_once(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        try:
            services = self.discover_services()
        except OnvifError:
            return
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
        self, *, url: str, content_type: str, envelope: str, auth: httpx.Auth | None
    ) -> tuple[int, str, str]:
        timeout = (
            self._timeout
            if self._read_override_s is None
            else httpx.Timeout(self._timeout, read=self._read_override_s)
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

    def _post_soap(self, *, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        status, text, challenge = self._raw_post(
            url=url, content_type=content_type, envelope=envelope, auth=None
        )
        if status == 401:
            auth = self._http_auth_for(challenge)
            if auth is not None:
                status, text, _ = self._raw_post(
                    url=url, content_type=content_type, envelope=envelope, auth=auth
                )
        return status, text

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + random.random()
        return float(min(2.0, 0.25 * (2**attempt)) * jitter)

    def _send_cycle(self, *, xaddr: str, operation: str, envelope: str) -> str:
        last_status = 0
        last_text = ""
        for ct in _CONTENT_TYPES:
            try:
                status, text = self._post_soap(url=xaddr, envelope=envelope, content_type=ct)
            except httpx.TimeoutException as exc:
                if self._read_override_s is None:
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
    ) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        text_mode = self._password_text if password_text is None else password_text
        long_poll = self._read_override_s is not None
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
                return self._send_cycle(xaddr=xaddr, operation=operation, envelope=envelope)
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
                )
            raise

    def _sync_clock_offset(self) -> None:
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

    def get_device_information(self) -> dict[str, str]:
        """Return the ONVIF ``GetDeviceInformation`` result from the Device service, parsed by ``parsers.parse_device_information`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetDeviceInformation",
            body_inner=envelopes.device_get_information(),
        )
        return parsers.parse_device_information(xml)

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
        """Return the device's service-to-XAddr map, trying ``GetServices`` first and falling back to ``GetCapabilities``."""
        try:
            services = self.get_services()
            if services:
                return services
        except OnvifFaultError:
            services = {}
        return self.get_capabilities()

    def get_system_date_time(self) -> dict[str, Any]:
        """Return the ONVIF ``GetSystemDateAndTime`` result from the Device service, parsed by ``parsers.parse_system_datetime`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetSystemDateAndTime",
            body_inner=envelopes.device_get_system_date_time(),
        )
        return parsers.parse_system_datetime(xml)

    def set_system_date_time(
        self,
        *,
        date_time_type: str = "Manual",
        daylight_savings: bool = False,
        timezone: str = "",
        utc_datetime: datetime | None = None,
    ) -> None:
        """Send the ONVIF ``SetSystemDateAndTime`` request to the Device service."""
        self.call(
            service="device",
            operation="SetSystemDateAndTime",
            body_inner=envelopes.device_set_system_date_time(
                date_time_type=date_time_type,
                daylight_savings=daylight_savings,
                timezone=timezone,
                utc_datetime=utc_datetime,
            ),
        )

    def get_hostname(self) -> str:
        """Return the ONVIF ``GetHostname`` result from the Device service, parsed by ``parsers.parse_hostname`` into ``str``."""
        xml = self.call(
            service="device",
            operation="GetHostname",
            body_inner=envelopes.device_get_hostname(),
        )
        return parsers.parse_hostname(xml)

    def set_hostname(self, name: str) -> None:
        """Send the ONVIF ``SetHostname`` request to the Device service."""
        self.call(
            service="device",
            operation="SetHostname",
            body_inner=envelopes.device_set_hostname(name),
        )

    def get_network_interfaces(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetNetworkInterfaces`` result from the Device service, parsed by ``parsers.parse_network_interfaces`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkInterfaces",
            body_inner=envelopes.device_get_network_interfaces(),
        )
        return parsers.parse_network_interfaces(xml)

    def get_users(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetUsers`` result from the Device service, parsed by ``parsers.parse_users`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetUsers",
            body_inner=envelopes.device_get_users(),
        )
        return parsers.parse_users(xml)

    def system_reboot(self) -> None:
        """Send the ONVIF ``SystemReboot`` request to the Device service."""
        self.call(
            service="device",
            operation="SystemReboot",
            body_inner=envelopes.device_system_reboot(),
        )

    def system_factory_default(self, *, hard: bool = False) -> None:
        """Send the ONVIF ``SetSystemFactoryDefault`` request to the Device service."""
        self.call(
            service="device",
            operation="SetSystemFactoryDefault",
            body_inner=envelopes.device_set_system_factory_default(hard=hard),
        )

    def create_user(self, *, username: str, password: str, user_level: str) -> None:
        """Send the ONVIF ``CreateUsers`` request to the Device service."""
        self.call(
            service="device",
            operation="CreateUsers",
            body_inner=envelopes.device_create_users(
                username=username, password=password, user_level=user_level
            ),
        )

    def set_user(self, *, username: str, password: str, user_level: str) -> None:
        """Send the ONVIF ``SetUser`` request to the Device service."""
        self.call(
            service="device",
            operation="SetUser",
            body_inner=envelopes.device_set_user(
                username=username, password=password, user_level=user_level
            ),
        )

    def delete_users(self, *, usernames: list[str]) -> None:
        """Send the ONVIF ``DeleteUsers`` request to the Device service."""
        self.call(
            service="device",
            operation="DeleteUsers",
            body_inner=envelopes.device_delete_users(usernames=usernames),
        )

    def set_network_interface(
        self,
        *,
        token: str,
        enabled: bool,
        dhcp: bool,
        ipv4_address: str = "",
        prefix_length: int = 24,
        mtu: int | None = None,
    ) -> None:
        """Send the ONVIF ``SetNetworkInterfaces`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNetworkInterfaces",
            body_inner=envelopes.device_set_network_interface(
                token=token,
                enabled=enabled,
                dhcp=dhcp,
                ipv4_address=ipv4_address,
                prefix_length=prefix_length,
                mtu=mtu,
            ),
        )

    def get_network_protocols(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetNetworkProtocols`` result from the Device service, parsed by ``parsers.parse_network_protocols`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkProtocols",
            body_inner=envelopes.device_get_network_protocols(),
        )
        return parsers.parse_network_protocols(xml)

    def set_network_protocols(self, *, protocols: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``SetNetworkProtocols`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNetworkProtocols",
            body_inner=envelopes.device_set_network_protocols(protocols=protocols),
        )

    def get_network_default_gateway(self) -> dict[str, list[str]]:
        """Return the ONVIF ``GetNetworkDefaultGateway`` result from the Device service, parsed by ``parsers.parse_network_default_gateway`` into ``dict[str, list[str]]``."""
        xml = self.call(
            service="device",
            operation="GetNetworkDefaultGateway",
            body_inner=envelopes.device_get_network_default_gateway(),
        )
        return parsers.parse_network_default_gateway(xml)

    def set_network_default_gateway(self, *, ipv4_addresses: list[str]) -> None:
        """Send the ONVIF ``SetNetworkDefaultGateway`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNetworkDefaultGateway",
            body_inner=envelopes.device_set_network_default_gateway(ipv4_addresses=ipv4_addresses),
        )

    def create_profile(self, *, name: str, token: str = "") -> str:
        """Return the ONVIF ``CreateProfile`` result from the Media service, parsed by ``parsers.parse_profile_create`` into ``str``."""
        service, _ = self._media_service()
        xml = self.call(
            service=service,
            operation="CreateProfile",
            body_inner=envelopes.media_create_profile(name=name, token=token),
        )
        return parsers.parse_profile_create(xml) or token

    def delete_profile(self, *, profile_token: str) -> None:
        """Send the ONVIF ``DeleteProfile`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="DeleteProfile",
            body_inner=envelopes.media_delete_profile(profile_token=profile_token),
        )

    def add_video_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddVideoSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddVideoSourceConfiguration",
            body_inner=envelopes.media_add_video_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def add_video_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddVideoEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddVideoEncoderConfiguration",
            body_inner=envelopes.media_add_video_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_video_encoder_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveVideoEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveVideoEncoderConfiguration",
            body_inner=envelopes.media_remove_video_encoder_configuration(
                profile_token=profile_token
            ),
        )

    def add_ptz_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Send the ONVIF ``AddPTZConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddPTZConfiguration",
            body_inner=envelopes.media_add_ptz_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_ptz_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemovePTZConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemovePTZConfiguration",
            body_inner=envelopes.media_remove_ptz_configuration(profile_token=profile_token),
        )

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

    def get_profiles(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetProfiles`` result from the Media service, parsed by ``parsers.parse_profiles`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetProfiles",
            body_inner=envelopes.media_get_profiles(use_media2=use_media2),
        )
        return parsers.parse_profiles(xml)

    def get_video_sources(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetVideoSources`` result from the Media service, parsed by ``parsers.parse_video_sources`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoSources",
            body_inner=envelopes.media_get_video_sources(use_media2=use_media2),
        )
        return parsers.parse_video_sources(xml)

    def get_video_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the list of video encoder configurations, preferring the Media2 service and falling back to legacy Media."""
        prefer_media2 = self._has("media2")
        if prefer_media2:
            try:
                xml = self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurations",
                    body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
                )
                configs = parsers.parse_video_encoder_configurations(xml)
                if configs:
                    return configs
            except OnvifCapabilityMissingError:
                pass
        if self._has("media"):
            xml = self.call(
                service="media",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=False),
            )
            return parsers.parse_video_encoder_configurations(xml)
        if prefer_media2:
            xml = self.call(
                service="media2",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
            )
            return parsers.parse_video_encoder_configurations(xml)
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    def get_stream_uri(
        self,
        *,
        profile_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
        protocol2: str = "RtspUnicast",
    ) -> str:
        """Return the ONVIF ``GetStreamUri`` result from the Media service, parsed by ``parsers.parse_stream_uri`` into ``str``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetStreamUri",
            body_inner=envelopes.media_get_stream_uri(
                profile_token=profile_token,
                use_media2=use_media2,
                stream=stream,
                protocol=protocol,
                protocol2=protocol2,
            ),
        )
        return parsers.parse_stream_uri(xml)

    def get_snapshot_uri(self, *, profile_token: str) -> str:
        """Return the ONVIF ``GetSnapshotUri`` result from the Media service, parsed by ``parsers.parse_snapshot_uri`` into ``str``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetSnapshotUri",
            body_inner=envelopes.media_get_snapshot_uri(
                profile_token=profile_token, use_media2=use_media2
            ),
        )
        return parsers.parse_snapshot_uri(xml)

    def get_snapshot(self, *, profile_token: str) -> tuple[bytes, str]:
        """Fetch a JPEG snapshot for a profile as ``(image_bytes, content_type)``.

        Resolves the snapshot URI then downloads it with the client's credentials and TLS
        setting (HTTP Digest auth, falling back to Basic).
        """
        uri = self.get_snapshot_uri(profile_token=profile_token)
        return fetch_snapshot_bytes(
            snapshot_uri=uri,
            credentials=self._credentials,
            timeout_s=self._timeout_s,
            verify_tls=self._verify_tls,
        )

    def set_video_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float,
        fps: int,
        bitrate_kbps: int,
        gop: int,
        h264_profile: str = "",
        force_persistence: bool = True,
    ) -> None:
        """Send the ONVIF ``SetVideoEncoderConfiguration`` request to the Media service."""
        if self._has("media"):
            service = "media"
        else:
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration is only supported via the legacy Media service."
            )
        self.call(
            service=service,
            operation="SetVideoEncoderConfiguration",
            body_inner=envelopes.media_set_video_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                width=width,
                height=height,
                quality=quality,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
                gop=gop,
                h264_profile=h264_profile,
                force_persistence=force_persistence,
            ),
        )

    def ptz_get_nodes(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetNodes`` result from the PTZ service, parsed by ``parsers.parse_ptz_nodes`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="ptz",
            operation="GetNodes",
            body_inner=envelopes.ptz_get_nodes(),
        )
        return parsers.parse_ptz_nodes(xml)

    def ptz_get_status(self, *, profile_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetStatus`` result from the PTZ service, parsed by ``parsers.parse_ptz_status`` into ``dict[str, Any]``."""
        xml = self.call(
            service="ptz",
            operation="GetStatus",
            body_inner=envelopes.ptz_get_status(profile_token=profile_token),
        )
        return parsers.parse_ptz_status(xml)

    def ptz_continuous_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        timeout: str = "",
    ) -> None:
        """Send the ONVIF ``ContinuousMove`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="ContinuousMove",
            body_inner=envelopes.ptz_continuous_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                timeout=timeout,
            ),
        )

    def ptz_absolute_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Send the ONVIF ``AbsoluteMove`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="AbsoluteMove",
            body_inner=envelopes.ptz_absolute_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    def ptz_relative_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Send the ONVIF ``RelativeMove`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="RelativeMove",
            body_inner=envelopes.ptz_relative_move(
                profile_token=profile_token,
                pan=pan,
                tilt=tilt,
                zoom=zoom,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    def ptz_stop(self, *, profile_token: str, pan_tilt: bool = True, zoom: bool = True) -> None:
        """Send the ONVIF ``Stop`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="Stop",
            body_inner=envelopes.ptz_stop(
                profile_token=profile_token, pan_tilt=pan_tilt, zoom=zoom
            ),
        )

    def ptz_get_presets(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetPresets`` result from the PTZ service, parsed by ``parsers.parse_ptz_presets`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="ptz",
            operation="GetPresets",
            body_inner=envelopes.ptz_get_presets(profile_token=profile_token),
        )
        return parsers.parse_ptz_presets(xml)

    def ptz_set_preset(
        self,
        *,
        profile_token: str,
        preset_name: str = "",
        preset_token: str = "",
    ) -> str:
        """Return the ONVIF ``SetPreset`` result from the PTZ service, parsed by ``parsers.parse_set_preset_token`` into ``str``."""
        xml = self.call(
            service="ptz",
            operation="SetPreset",
            body_inner=envelopes.ptz_set_preset(
                profile_token=profile_token,
                preset_name=preset_name,
                preset_token=preset_token,
            ),
        )
        return parsers.parse_set_preset_token(xml) or preset_token

    def ptz_remove_preset(self, *, profile_token: str, preset_token: str) -> None:
        """Send the ONVIF ``RemovePreset`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="RemovePreset",
            body_inner=envelopes.ptz_remove_preset(
                profile_token=profile_token, preset_token=preset_token
            ),
        )

    def ptz_goto_preset(
        self,
        *,
        profile_token: str,
        preset_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Send the ONVIF ``GotoPreset`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="GotoPreset",
            body_inner=envelopes.ptz_goto_preset(
                profile_token=profile_token,
                preset_token=preset_token,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    def ptz_set_home_position(self, *, profile_token: str) -> None:
        """Send the ONVIF ``SetHomePosition`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="SetHomePosition",
            body_inner=envelopes.ptz_set_home_position(profile_token=profile_token),
        )

    def ptz_goto_home_position(
        self,
        *,
        profile_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Send the ONVIF ``GotoHomePosition`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="GotoHomePosition",
            body_inner=envelopes.ptz_goto_home_position(
                profile_token=profile_token,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    def imaging_get_settings(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetImagingSettings`` result from the Imaging service, parsed by ``parsers.parse_imaging_settings`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetImagingSettings",
            body_inner=envelopes.imaging_get_settings(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_settings(xml)

    def imaging_get_options(self, *, video_source_token: str) -> str:
        """Return the raw ``GetOptions`` response XML from the Imaging service."""
        return self.call(
            service="imaging",
            operation="GetOptions",
            body_inner=envelopes.imaging_get_options(video_source_token=video_source_token),
        )

    def imaging_get_status(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetStatus`` result from the Imaging service, parsed by ``parsers.parse_imaging_status`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetStatus",
            body_inner=envelopes.imaging_get_status(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_status(xml)

    def imaging_set_settings(self, *, video_source_token: str, **kwargs: Any) -> None:
        """Send the ONVIF ``SetImagingSettings`` request to the Imaging service."""
        body = envelopes.imaging_set_settings(video_source_token=video_source_token, **kwargs)
        self.call(
            service="imaging",
            operation="SetImagingSettings",
            body_inner=body,
        )

    def imaging_move(
        self,
        *,
        video_source_token: str,
        focus_continuous: float | None = None,
        focus_absolute: float | None = None,
        focus_relative: float | None = None,
        speed: float | None = None,
    ) -> None:
        """Send the ONVIF ``Move`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="Move",
            body_inner=envelopes.imaging_move(
                video_source_token=video_source_token,
                focus_continuous=focus_continuous,
                focus_absolute=focus_absolute,
                focus_relative=focus_relative,
                speed=speed,
            ),
        )

    def imaging_stop(self, *, video_source_token: str) -> None:
        """Send the ONVIF ``Stop`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="Stop",
            body_inner=envelopes.imaging_stop(video_source_token=video_source_token),
        )

    def imaging_get_options_parsed(self, *, video_source_token: str) -> dict[str, Any]:
        """Return imaging setting options for ``video_source_token`` as a parsed dict (wraps ``imaging_get_options`` + ``parsers.parse_imaging_options``)."""
        xml = self.imaging_get_options(video_source_token=video_source_token)
        return parsers.parse_imaging_options(xml)

    def get_audio_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioEncoderConfigurations`` result from the Media service, parsed by ``parsers.parse_audio_encoder_configurations`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetAudioEncoderConfigurations",
            body_inner=envelopes.media_get_audio_encoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_encoder_configurations(xml)

    def set_audio_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        bitrate_kbps: int,
        sample_rate: int,
        force_persistence: bool = True,
    ) -> None:
        """Send the ONVIF ``SetAudioEncoderConfiguration`` request to the Media service."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioEncoderConfiguration is only supported via the legacy Media service."
            )
        self.call(
            service="media",
            operation="SetAudioEncoderConfiguration",
            body_inner=envelopes.media_set_audio_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                bitrate_kbps=bitrate_kbps,
                sample_rate=sample_rate,
                force_persistence=force_persistence,
            ),
        )

    def get_audio_sources(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioSources`` result from the Media service, parsed by ``parsers.parse_audio_sources`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioSources requires the legacy Media service.")
        xml = self.call(
            service="media",
            operation="GetAudioSources",
            body_inner=envelopes.media_get_audio_sources(),
        )
        return parsers.parse_audio_sources(xml)

    def get_audio_outputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioOutputs`` result from the Media service, parsed by ``parsers.parse_audio_outputs`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioOutputs requires the legacy Media service.")
        xml = self.call(
            service="media",
            operation="GetAudioOutputs",
            body_inner=envelopes.media_get_audio_outputs(),
        )
        return parsers.parse_audio_outputs(xml)

    def get_audio_output_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAudioOutputConfigurations`` result from the Media service, parsed by ``parsers.parse_audio_output_configurations`` into ``list[dict[str, Any]]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetAudioOutputConfigurations requires the legacy Media service."
            )
        xml = self.call(
            service="media",
            operation="GetAudioOutputConfigurations",
            body_inner=envelopes.media_get_audio_output_configurations(),
        )
        return parsers.parse_audio_output_configurations(xml)

    def set_audio_output_configuration(
        self,
        *,
        token: str,
        name: str,
        output_token: str,
        output_level: int,
        send_primacy: str = "",
        use_count: int = 0,
        force_persistence: bool = True,
    ) -> None:
        """Send the ONVIF ``SetAudioOutputConfiguration`` request to the Media service."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioOutputConfiguration requires the legacy Media service."
            )
        self.call(
            service="media",
            operation="SetAudioOutputConfiguration",
            body_inner=envelopes.media_set_audio_output_configuration(
                token=token,
                name=name,
                output_token=output_token,
                output_level=output_level,
                send_primacy=send_primacy,
                use_count=use_count,
                force_persistence=force_persistence,
            ),
        )

    def get_relay_outputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRelayOutputs`` result from the Device service, parsed by ``parsers.parse_relay_outputs`` into ``list[dict[str, Any]]``."""
        service, use_deviceio = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetRelayOutputs",
            body_inner=envelopes.device_get_relay_outputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_relay_outputs(xml)

    def set_relay_output_state(self, *, token: str, logical_state: str) -> None:
        """Send the ONVIF ``SetRelayOutputState`` request to the Device service."""
        service, use_deviceio = self._relay_service()
        self.call(
            service=service,
            operation="SetRelayOutputState",
            body_inner=envelopes.device_set_relay_output_state(
                token=token, logical_state=logical_state, use_deviceio=use_deviceio
            ),
        )

    def set_relay_output_settings(
        self,
        *,
        token: str,
        mode: str,
        delay_time: str,
        idle_state: str,
    ) -> None:
        """Send the ONVIF ``SetRelayOutputSettings`` request to the Device service."""
        service, use_deviceio = self._relay_service()
        self.call(
            service=service,
            operation="SetRelayOutputSettings",
            body_inner=envelopes.device_set_relay_output_settings(
                token=token,
                mode=mode,
                delay_time=delay_time,
                idle_state=idle_state,
                use_deviceio=use_deviceio,
            ),
        )

    def get_video_encoder_options(
        self, *, configuration_token: str, profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetVideoEncoderConfigurationOptions`` result from the Media service, parsed by ``parsers.parse_video_encoder_options`` into ``dict[str, Any]``."""
        if not self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetVideoEncoderConfigurationOptions requires the legacy Media service."
            )
        xml = self.call(
            service="media",
            operation="GetVideoEncoderConfigurationOptions",
            body_inner=envelopes.media_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    def get_video_encoder_options_raw(
        self,
        *,
        configuration_token: str = "",
        profile_token: str = "",
        prefer: str = "auto",
    ) -> tuple[str, str]:
        """Return ``(service_name, response_xml)`` for ``GetVideoEncoderConfigurationOptions``, selecting Media2 or Media per ``prefer``."""
        if prefer == "media2" and self._has("media2"):
            return (
                "media2",
                self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if self._has("media"):
            return (
                "media",
                self.call(
                    service="media",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if self._has("media2"):
            return (
                "media2",
                self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        raise OnvifCapabilityMissingError(
            "GetVideoEncoderConfigurationOptions requires a Media or Media2 service."
        )

    def set_video_encoder_configuration_media2(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        width: int,
        height: int,
        quality: float | None,
        fps: int | None,
        bitrate_kbps: int | None,
        gop: int | None,
        h264_profile: str = "",
        h265_profile: str = "",
        use_count: int = 0,
    ) -> None:
        """Send the ONVIF ``SetVideoEncoderConfiguration`` request to the Media2 service."""
        if not self._has("media2"):
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration (Media2) requires the Media2 service."
            )
        self.call(
            service="media2",
            operation="SetVideoEncoderConfiguration",
            body_inner=envelopes.media2_set_video_encoder_configuration(
                token=token,
                name=name,
                encoding=encoding,
                width=width,
                height=height,
                quality=quality,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
                gop=gop,
                h264_profile=h264_profile,
                h265_profile=h265_profile,
                use_count=use_count,
            ),
        )

    def get_video_analytics_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetVideoAnalyticsConfigurations`` result from the Media service, parsed by ``parsers.parse_video_analytics_configurations`` into ``list[dict[str, Any]]``."""
        service, use_media2 = self._media_service()
        xml = self.call(
            service=service,
            operation="GetVideoAnalyticsConfigurations",
            body_inner=envelopes.media_get_video_analytics_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_analytics_configurations(xml)

    def ptz_get_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetConfigurations`` result from the PTZ service, parsed by ``parsers.parse_ptz_configurations`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="ptz",
            operation="GetConfigurations",
            body_inner=envelopes.ptz_get_configurations(),
        )
        return parsers.parse_ptz_configurations(xml)

    def get_dns(self) -> dict[str, Any]:
        """Return the ONVIF ``GetDNS`` result from the Device service, parsed by ``parsers.parse_dns`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetDNS",
            body_inner=envelopes.device_get_dns(),
        )
        return parsers.parse_dns(xml)

    def set_dns(
        self,
        *,
        from_dhcp: bool,
        ipv4_servers: list[str],
        search_domains: list[str],
    ) -> None:
        """Send the ONVIF ``SetDNS`` request to the Device service."""
        self.call(
            service="device",
            operation="SetDNS",
            body_inner=envelopes.device_set_dns(
                from_dhcp=from_dhcp,
                ipv4_servers=ipv4_servers,
                search_domains=search_domains,
            ),
        )

    def get_ntp(self) -> dict[str, Any]:
        """Return the ONVIF ``GetNTP`` result from the Device service, parsed by ``parsers.parse_ntp`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetNTP",
            body_inner=envelopes.device_get_ntp(),
        )
        return parsers.parse_ntp(xml)

    def set_ntp(self, *, from_dhcp: bool, ipv4_servers: list[str]) -> None:
        """Send the ONVIF ``SetNTP`` request to the Device service."""
        self.call(
            service="device",
            operation="SetNTP",
            body_inner=envelopes.device_set_ntp(from_dhcp=from_dhcp, ipv4_servers=ipv4_servers),
        )

    def analytics_get_supported_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetSupportedRules`` result from the Analytics service, parsed by ``parsers.parse_rules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetSupportedRules",
            body_inner=envelopes.analytics_get_supported_rules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_rules(xml)

    def analytics_get_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRules`` result from the Analytics service, parsed by ``parsers.parse_rules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetRules",
            body_inner=envelopes.analytics_get_rules(configuration_token=configuration_token),
        )
        return parsers.parse_rules(xml)

    def analytics_get_supported_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetSupportedAnalyticsModules`` result from the Analytics service, parsed by ``parsers.parse_analytics_modules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetSupportedAnalyticsModules",
            body_inner=envelopes.analytics_get_supported_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

    def analytics_get_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetAnalyticsModules`` result from the Analytics service, parsed by ``parsers.parse_analytics_modules`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="analytics",
            operation="GetAnalyticsModules",
            body_inner=envelopes.analytics_get_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

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
        """Return the ONVIF ``CreatePullPointSubscription`` result from the Events service, parsed by ``parsers.parse_create_pull_point`` into ``dict[str, Any]``."""
        xml = self.call(
            service="events",
            operation="CreatePullPointSubscription",
            body_inner=envelopes.events_create_pull_point_subscription(
                termination_time=termination_time, topic_filter=topic_filter
            ),
        )
        return parsers.parse_create_pull_point(xml)

    def _post_subscription(
        self, *, subscription_url: str, body: str, wsa_action: str, operation: str
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
            return self._post_xml(url=subscription_url, envelope=build(), operation=operation)
        except OnvifAuthError:
            if self._clock_synced or not self._credentials.configured:
                raise
            self._sync_clock_offset()
            if self._clock_offset_s == 0.0:
                raise
            return self._post_xml(url=subscription_url, envelope=build(), operation=operation)

    def events_pull_messages(
        self,
        *,
        subscription_url: str,
        timeout: str = "PT5S",
        message_limit: int = 20,
    ) -> dict[str, Any]:
        """Pull queued notifications from a PullPoint ``subscription_url`` and return the parsed messages and termination times as a dict."""
        prev_override = self._read_override_s
        self._read_override_s = _iso8601_seconds(timeout, 5.0) + 5.0
        try:
            xml = self._post_subscription(
                subscription_url=subscription_url,
                body=envelopes.events_pull_messages(timeout=timeout, message_limit=message_limit),
                wsa_action=(
                    "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
                ),
                operation="PullMessages",
            )
        finally:
            self._read_override_s = prev_override
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

    def _post_xml(self, *, url: str, envelope: str, operation: str) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        return self._send_cycle(xaddr=url, operation=operation, envelope=envelope)

    def _require_media1(self, operation: str) -> None:
        if not self._has("media"):
            raise OnvifCapabilityMissingError(f"{operation} requires the legacy Media service.")

    def get_recordings(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRecordings`` result from the Recording service, parsed by ``parsers.parse_recordings`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="recording",
            operation="GetRecordings",
            body_inner=envelopes.recording_get_recordings(),
        )
        return parsers.parse_recordings(xml)

    def create_recording(
        self,
        *,
        source_id: str,
        source_name: str,
        source_location: str = "",
        source_description: str = "",
        source_address: str = "",
        content: str = "",
        max_retention: str = "PT0S",
    ) -> str:
        """Return the ONVIF ``CreateRecording`` result from the Recording service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="recording",
            operation="CreateRecording",
            body_inner=envelopes.recording_create_recording(
                source_id=source_id,
                source_name=source_name,
                source_location=source_location,
                source_description=source_description,
                source_address=source_address,
                content=content,
                max_retention=max_retention,
            ),
        )
        return parsers.parse_created_token(xml, tag="RecordingToken")

    def delete_recording(self, *, recording_token: str) -> None:
        """Send the ONVIF ``DeleteRecording`` request to the Recording service."""
        self.call(
            service="recording",
            operation="DeleteRecording",
            body_inner=envelopes.recording_delete_recording(recording_token=recording_token),
        )

    def get_recording_configuration(self, *, recording_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetRecordingConfiguration`` result from the Recording service, parsed by ``parsers.parse_recording_configuration`` into ``dict[str, Any]``."""
        xml = self.call(
            service="recording",
            operation="GetRecordingConfiguration",
            body_inner=envelopes.recording_get_recording_configuration(
                recording_token=recording_token
            ),
        )
        return parsers.parse_recording_configuration(xml)

    def set_recording_configuration(
        self,
        *,
        recording_token: str,
        source_id: str,
        source_name: str,
        source_location: str = "",
        source_description: str = "",
        source_address: str = "",
        content: str = "",
        max_retention: str = "PT0S",
    ) -> None:
        """Send the ONVIF ``SetRecordingConfiguration`` request to the Recording service."""
        self.call(
            service="recording",
            operation="SetRecordingConfiguration",
            body_inner=envelopes.recording_set_recording_configuration(
                recording_token=recording_token,
                source_id=source_id,
                source_name=source_name,
                source_location=source_location,
                source_description=source_description,
                source_address=source_address,
                content=content,
                max_retention=max_retention,
            ),
        )

    def get_recording_jobs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRecordingJobs`` result from the Recording service, parsed by ``parsers.parse_recording_jobs`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="recording",
            operation="GetRecordingJobs",
            body_inner=envelopes.recording_get_recording_jobs(),
        )
        return parsers.parse_recording_jobs(xml)

    def create_recording_job(
        self,
        *,
        recording_token: str,
        mode: str = "Active",
        priority: int = 10,
        source_token: str = "",
        source_type: str = "",
    ) -> str:
        """Return the ONVIF ``CreateRecordingJob`` result from the Recording service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="recording",
            operation="CreateRecordingJob",
            body_inner=envelopes.recording_create_recording_job(
                recording_token=recording_token,
                mode=mode,
                priority=priority,
                source_token=source_token,
                source_type=source_type,
            ),
        )
        return parsers.parse_created_token(xml, tag="JobToken")

    def delete_recording_job(self, *, job_token: str) -> None:
        """Send the ONVIF ``DeleteRecordingJob`` request to the Recording service."""
        self.call(
            service="recording",
            operation="DeleteRecordingJob",
            body_inner=envelopes.recording_delete_recording_job(job_token=job_token),
        )

    def set_recording_job_mode(self, *, job_token: str, mode: str) -> None:
        """Send the ONVIF ``SetRecordingJobMode`` request to the Recording service."""
        self.call(
            service="recording",
            operation="SetRecordingJobMode",
            body_inner=envelopes.recording_set_recording_job_mode(job_token=job_token, mode=mode),
        )

    def get_recording_summary(self) -> dict[str, Any]:
        """Return the ONVIF ``GetRecordingSummary`` result from the Search service, parsed by ``parsers.parse_recording_summary`` into ``dict[str, Any]``."""
        xml = self.call(
            service="search",
            operation="GetRecordingSummary",
            body_inner=envelopes.search_get_recording_summary(),
        )
        return parsers.parse_recording_summary(xml)

    def find_recordings(
        self,
        *,
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Return the ONVIF ``FindRecordings`` result from the Search service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="search",
            operation="FindRecordings",
            body_inner=envelopes.search_find_recordings(
                included_sources=included_sources,
                included_recordings=included_recordings,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    def get_recording_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetRecordingSearchResults`` result from the Search service, parsed by ``parsers.parse_recording_search_results`` into ``dict[str, Any]``."""
        xml = self.call(
            service="search",
            operation="GetRecordingSearchResults",
            body_inner=envelopes.search_get_recording_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_recording_search_results(xml)

    def find_events(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        include_start_state: bool = False,
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Return the ONVIF ``FindEvents`` result from the Search service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="search",
            operation="FindEvents",
            body_inner=envelopes.search_find_events(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                include_start_state=include_start_state,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    def get_event_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetEventSearchResults`` result from the Search service, parsed by ``parsers.parse_event_search_results`` into ``dict[str, Any]``."""
        xml = self.call(
            service="search",
            operation="GetEventSearchResults",
            body_inner=envelopes.search_get_event_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_event_search_results(xml)

    def find_ptz_position(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Return the ONVIF ``FindPTZPosition`` result from the Search service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="search",
            operation="FindPTZPosition",
            body_inner=envelopes.search_find_ptz_position(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    def get_ptz_position_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetPTZPositionSearchResults`` result from the Search service, parsed by ``parsers.parse_ptz_position_search_results`` into ``dict[str, Any]``."""
        xml = self.call(
            service="search",
            operation="GetPTZPositionSearchResults",
            body_inner=envelopes.search_get_ptz_position_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_ptz_position_search_results(xml)

    def find_metadata(
        self,
        *,
        start_point: str,
        end_point: str = "",
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        filter_expression: str = "",
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Return the ONVIF ``FindMetadata`` result from the Search service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="search",
            operation="FindMetadata",
            body_inner=envelopes.search_find_metadata(
                start_point=start_point,
                end_point=end_point,
                included_sources=included_sources,
                included_recordings=included_recordings,
                filter_expression=filter_expression,
                max_matches=max_matches,
                keep_alive=keep_alive,
            ),
        )
        return parsers.parse_created_token(xml, tag="SearchToken")

    def get_metadata_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetMetadataSearchResults`` result from the Search service, parsed by ``parsers.parse_metadata_search_results`` into ``dict[str, Any]``."""
        xml = self.call(
            service="search",
            operation="GetMetadataSearchResults",
            body_inner=envelopes.search_get_metadata_search_results(
                search_token=search_token,
                min_results=min_results,
                max_results=max_results,
                wait_time=wait_time,
            ),
        )
        return parsers.parse_metadata_search_results(xml)

    def end_search(self, *, search_token: str) -> None:
        """Send the ONVIF ``EndSearch`` request to the Search service."""
        self.call(
            service="search",
            operation="EndSearch",
            body_inner=envelopes.search_end_search(search_token=search_token),
        )

    def get_replay_uri(
        self,
        *,
        recording_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
    ) -> str:
        """Return the ONVIF ``GetReplayUri`` result from the Replay service, parsed by ``parsers.parse_stream_uri`` into ``str``."""
        xml = self.call(
            service="replay",
            operation="GetReplayUri",
            body_inner=envelopes.replay_get_replay_uri(
                recording_token=recording_token, stream=stream, protocol=protocol
            ),
        )
        return parsers.parse_stream_uri(xml)

    def get_replay_configuration(self) -> dict[str, Any]:
        """Return the ONVIF ``GetReplayConfiguration`` result from the Replay service, parsed by ``parsers.parse_replay_configuration`` into ``dict[str, Any]``."""
        xml = self.call(
            service="replay",
            operation="GetReplayConfiguration",
            body_inner=envelopes.replay_get_replay_configuration(),
        )
        return parsers.parse_replay_configuration(xml)

    def set_replay_configuration(self, *, session_timeout: str = "PT60S") -> None:
        """Send the ONVIF ``SetReplayConfiguration`` request to the Replay service."""
        self.call(
            service="replay",
            operation="SetReplayConfiguration",
            body_inner=envelopes.replay_set_replay_configuration(session_timeout=session_timeout),
        )

    def get_osds(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the ONVIF ``GetOSDs`` result from the Media service, parsed by ``parsers.parse_osds`` into ``list[dict[str, Any]]``."""
        self._require_media1("GetOSDs")
        xml = self.call(
            service="media",
            operation="GetOSDs",
            body_inner=envelopes.media_get_osds(configuration_token=configuration_token),
        )
        return parsers.parse_osds(xml)

    def get_osd(self, *, osd_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetOSD`` result from the Media service, parsed by ``parsers.parse_osd`` into ``dict[str, Any]``."""
        self._require_media1("GetOSD")
        xml = self.call(
            service="media",
            operation="GetOSD",
            body_inner=envelopes.media_get_osd(osd_token=osd_token),
        )
        return parsers.parse_osd(xml)

    def get_osd_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetOSDOptions`` result from the Media service, parsed by ``parsers.parse_osd_options`` into ``dict[str, Any]``."""
        self._require_media1("GetOSDOptions")
        xml = self.call(
            service="media",
            operation="GetOSDOptions",
            body_inner=envelopes.media_get_osd_options(configuration_token=configuration_token),
        )
        return parsers.parse_osd_options(xml)

    def create_osd(self, **kwargs: Any) -> str:
        """Return the ONVIF ``CreateOSD`` result from the Media service, parsed by ``parsers.parse_created_token`` into ``str``."""
        self._require_media1("CreateOSD")
        xml = self.call(
            service="media",
            operation="CreateOSD",
            body_inner=envelopes.media_create_osd(**kwargs),
        )
        return parsers.parse_created_token(xml, tag="OSDToken")

    def set_osd(self, **kwargs: Any) -> None:
        """Send the ONVIF ``SetOSD`` request to the Media service."""
        self._require_media1("SetOSD")
        self.call(
            service="media",
            operation="SetOSD",
            body_inner=envelopes.media_set_osd(**kwargs),
        )

    def delete_osd(self, *, osd_token: str) -> None:
        """Send the ONVIF ``DeleteOSD`` request to the Media service."""
        self._require_media1("DeleteOSD")
        self.call(
            service="media",
            operation="DeleteOSD",
            body_inner=envelopes.media_delete_osd(osd_token=osd_token),
        )

    def get_metadata_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetMetadataConfigurations`` result from the Media service, parsed by ``parsers.parse_metadata_configurations`` into ``list[dict[str, Any]]``."""
        self._require_media1("GetMetadataConfigurations")
        xml = self.call(
            service="media",
            operation="GetMetadataConfigurations",
            body_inner=envelopes.media_get_metadata_configurations(),
        )
        return parsers.parse_metadata_configurations(xml)

    def get_metadata_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetMetadataConfiguration`` result from the Media service, parsed by ``parsers.parse_metadata_configuration`` into ``dict[str, Any]``."""
        self._require_media1("GetMetadataConfiguration")
        xml = self.call(
            service="media",
            operation="GetMetadataConfiguration",
            body_inner=envelopes.media_get_metadata_configuration(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_metadata_configuration(xml)

    def get_metadata_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetMetadataConfigurationOptions`` result from the Media service, parsed by ``parsers.parse_video_encoder_options`` into ``dict[str, Any]``."""
        self._require_media1("GetMetadataConfigurationOptions")
        xml = self.call(
            service="media",
            operation="GetMetadataConfigurationOptions",
            body_inner=envelopes.media_get_metadata_configuration_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    def set_metadata_configuration(
        self,
        *,
        token: str,
        name: str,
        analytics: bool = True,
        ptz_status: bool = False,
        ptz_position: bool = False,
        use_count: int = 0,
    ) -> None:
        """Send the ONVIF ``SetMetadataConfiguration`` request to the Media service."""
        self._require_media1("SetMetadataConfiguration")
        self.call(
            service="media",
            operation="SetMetadataConfiguration",
            body_inner=envelopes.media_set_metadata_configuration(
                token=token,
                name=name,
                analytics=analytics,
                ptz_status=ptz_status,
                ptz_position=ptz_position,
                use_count=use_count,
            ),
        )

    def add_metadata_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Send the ONVIF ``AddMetadataConfiguration`` request to the Media service."""
        self._require_media1("AddMetadataConfiguration")
        self.call(
            service="media",
            operation="AddMetadataConfiguration",
            body_inner=envelopes.media_add_metadata_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_metadata_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveMetadataConfiguration`` request to the Media service."""
        self._require_media1("RemoveMetadataConfiguration")
        self.call(
            service="media",
            operation="RemoveMetadataConfiguration",
            body_inner=envelopes.media_remove_metadata_configuration(profile_token=profile_token),
        )

    def create_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Send the ONVIF ``CreateAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="CreateAnalyticsModules",
            body_inner=envelopes.analytics_create_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    def modify_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Send the ONVIF ``ModifyAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="ModifyAnalyticsModules",
            body_inner=envelopes.analytics_modify_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    def delete_analytics_modules(self, *, configuration_token: str, names: list[str]) -> None:
        """Send the ONVIF ``DeleteAnalyticsModules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="DeleteAnalyticsModules",
            body_inner=envelopes.analytics_delete_analytics_modules(
                configuration_token=configuration_token, names=names
            ),
        )

    def create_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``CreateRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="CreateRules",
            body_inner=envelopes.analytics_create_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    def modify_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Send the ONVIF ``ModifyRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="ModifyRules",
            body_inner=envelopes.analytics_modify_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    def delete_rules(self, *, configuration_token: str, names: list[str]) -> None:
        """Send the ONVIF ``DeleteRules`` request to the Analytics service."""
        self.call(
            service="analytics",
            operation="DeleteRules",
            body_inner=envelopes.analytics_delete_rules(
                configuration_token=configuration_token, names=names
            ),
        )

    def add_audio_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddAudioSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddAudioSourceConfiguration",
            body_inner=envelopes.media_add_audio_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def add_audio_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Send the ONVIF ``AddAudioEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="AddAudioEncoderConfiguration",
            body_inner=envelopes.media_add_audio_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    def remove_audio_encoder_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveAudioEncoderConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveAudioEncoderConfiguration",
            body_inner=envelopes.media_remove_audio_encoder_configuration(
                profile_token=profile_token
            ),
        )

    def remove_audio_source_configuration(self, *, profile_token: str) -> None:
        """Send the ONVIF ``RemoveAudioSourceConfiguration`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="RemoveAudioSourceConfiguration",
            body_inner=envelopes.media_remove_audio_source_configuration(
                profile_token=profile_token
            ),
        )

    def start_multicast_streaming(self, *, profile_token: str) -> None:
        """Send the ONVIF ``StartMulticastStreaming`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="StartMulticastStreaming",
            body_inner=envelopes.media_start_multicast_streaming(profile_token=profile_token),
        )

    def stop_multicast_streaming(self, *, profile_token: str) -> None:
        """Send the ONVIF ``StopMulticastStreaming`` request to the Media service."""
        service, _ = self._media_service()
        self.call(
            service=service,
            operation="StopMulticastStreaming",
            body_inner=envelopes.media_stop_multicast_streaming(profile_token=profile_token),
        )

    def ptz_send_auxiliary_command(self, *, profile_token: str, auxiliary_data: str) -> None:
        """Send the ONVIF ``SendAuxiliaryCommand`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="SendAuxiliaryCommand",
            body_inner=envelopes.ptz_send_auxiliary_command(
                profile_token=profile_token, auxiliary_data=auxiliary_data
            ),
        )

    def get_digital_inputs(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetDigitalInputs`` result from the Device service, parsed by ``parsers.parse_digital_inputs`` into ``list[dict[str, Any]]``."""
        service, use_deviceio = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetDigitalInputs",
            body_inner=envelopes.device_get_digital_inputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_digital_inputs(xml)

    def get_scopes(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetScopes`` result from the Device service, parsed by ``parsers.parse_scopes`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetScopes",
            body_inner=envelopes.device_get_scopes(),
        )
        return parsers.parse_scopes(xml)

    def set_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``SetScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="SetScopes",
            body_inner=envelopes.device_set_scopes(scopes=scopes),
        )

    def add_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``AddScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="AddScopes",
            body_inner=envelopes.device_add_scopes(scopes=scopes),
        )

    def remove_scopes(self, *, scopes: list[str]) -> None:
        """Send the ONVIF ``RemoveScopes`` request to the Device service."""
        self.call(
            service="device",
            operation="RemoveScopes",
            body_inner=envelopes.device_remove_scopes(scopes=scopes),
        )

    def get_system_log(self, *, log_type: str = "System") -> dict[str, str]:
        """Return the ONVIF ``GetSystemLog`` result from the Device service, parsed by ``parsers.parse_system_log`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetSystemLog",
            body_inner=envelopes.device_get_system_log(log_type=log_type),
        )
        return parsers.parse_system_log(xml)

    def get_system_support_information(self) -> dict[str, str]:
        """Return the ONVIF ``GetSystemSupportInformation`` result from the Device service, parsed by ``parsers.parse_support_information`` into ``dict[str, str]``."""
        xml = self.call(
            service="device",
            operation="GetSystemSupportInformation",
            body_inner=envelopes.device_get_system_support_information(),
        )
        return parsers.parse_support_information(xml)

    def get_certificates(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetCertificates`` result from the Device service, parsed by ``parsers.parse_certificates`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="device",
            operation="GetCertificates",
            body_inner=envelopes.device_get_certificates(),
        )
        return parsers.parse_certificates(xml)

    def get_dot1x_configurations(self) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetDot1XConfigurations`` result from the Device service, parsed by ``parsers.parse_dot1x_configurations`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="device",
            operation="GetDot1XConfigurations",
            body_inner=envelopes.device_get_dot1x_configurations(),
        )
        return parsers.parse_dot1x_configurations(xml)

    def get_service_capabilities(self, service: str) -> dict[str, Any]:
        """Return the parsed ``GetServiceCapabilities`` response for ``service`` (``media`` resolves to Media or Media2 automatically)."""
        resolved = service
        if service == "media":
            resolved, _ = self._media_service()
        xml = self.call(
            service=resolved,
            operation="GetServiceCapabilities",
            body_inner=envelopes.get_service_capabilities(resolved),
        )
        return parsers.parse_service_capabilities(xml)

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

    def get_relay_output_options(self, *, token: str = "") -> list[dict[str, Any]]:
        """Return the ONVIF ``GetRelayOutputOptions`` result from the Device service, parsed by ``parsers.parse_relay_output_options`` into ``list[dict[str, Any]]``."""
        service, _ = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetRelayOutputOptions",
            body_inner=envelopes.device_get_relay_output_options(token=token),
        )
        return parsers.parse_relay_output_options(xml)

    def get_serial_ports(self) -> list[dict[str, str]]:
        """Return the ONVIF ``GetSerialPorts`` result from the Device service, parsed by ``parsers.parse_serial_ports`` into ``list[dict[str, str]]``."""
        service, _ = self._relay_service()
        xml = self.call(
            service=service,
            operation="GetSerialPorts",
            body_inner=envelopes.device_get_serial_ports(),
        )
        return parsers.parse_serial_ports(xml)

    def get_access_point_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetAccessPointInfoList`` result from the Access Control service, parsed by ``pacs.parse_access_point_info_list`` into ``dict[str, Any]``."""
        xml = self.call(
            service="accesscontrol",
            operation="GetAccessPointInfoList",
            body_inner=pacs.access_point_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_access_point_info_list(xml)

    def get_access_point_state(self, *, token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetAccessPointState`` result from the Access Control service, parsed by ``pacs.parse_access_point_state`` into ``dict[str, Any]``."""
        xml = self.call(
            service="accesscontrol",
            operation="GetAccessPointState",
            body_inner=pacs.access_point_state(token=token),
        )
        return pacs.parse_access_point_state(xml)

    def enable_access_point(self, *, token: str) -> None:
        """Send the ONVIF ``EnableAccessPoint`` request to the Access Control service."""
        self.call(
            service="accesscontrol",
            operation="EnableAccessPoint",
            body_inner=pacs.enable_access_point(token=token),
        )

    def disable_access_point(self, *, token: str) -> None:
        """Send the ONVIF ``DisableAccessPoint`` request to the Access Control service."""
        self.call(
            service="accesscontrol",
            operation="DisableAccessPoint",
            body_inner=pacs.disable_access_point(token=token),
        )

    def get_area_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetAreaInfoList`` result from the Access Control service, parsed by ``pacs.parse_area_info_list`` into ``dict[str, Any]``."""
        xml = self.call(
            service="accesscontrol",
            operation="GetAreaInfoList",
            body_inner=pacs.area_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_area_info_list(xml)

    def get_door_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetDoorInfoList`` result from the Door Control service, parsed by ``pacs.parse_door_info_list`` into ``dict[str, Any]``."""
        xml = self.call(
            service="doorcontrol",
            operation="GetDoorInfoList",
            body_inner=pacs.door_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_door_info_list(xml)

    def get_door_state(self, *, token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetDoorState`` result from the Door Control service, parsed by ``pacs.parse_door_state`` into ``dict[str, Any]``."""
        xml = self.call(
            service="doorcontrol",
            operation="GetDoorState",
            body_inner=pacs.door_state(token=token),
        )
        return pacs.parse_door_state(xml)

    def door_command(self, command: str, *, token: str) -> None:
        """Send door-control ``command`` (the ONVIF operation name, e.g. ``AccessDoor``) for door ``token``."""
        self.call(
            service="doorcontrol",
            operation=command,
            body_inner=pacs.door_action(command, token=token),
        )

    def access_door(self, *, token: str) -> None:
        """Issue the ``AccessDoor`` door-control command for door ``token``."""
        self.door_command("AccessDoor", token=token)

    def lock_door(self, *, token: str) -> None:
        """Issue the ``LockDoor`` door-control command for door ``token``."""
        self.door_command("LockDoor", token=token)

    def unlock_door(self, *, token: str) -> None:
        """Issue the ``UnlockDoor`` door-control command for door ``token``."""
        self.door_command("UnlockDoor", token=token)

    def get_credential_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return the ONVIF ``GetCredentialInfoList`` result from the Credential service, parsed by ``pacs.parse_credential_info_list`` into ``dict[str, Any]``."""
        xml = self.call(
            service="credential",
            operation="GetCredentialInfoList",
            body_inner=pacs.credential_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_credential_info_list(xml)

    def get_credential_state(self, *, token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetCredentialState`` result from the Credential service, parsed by ``pacs.parse_credential_state`` into ``dict[str, Any]``."""
        xml = self.call(
            service="credential",
            operation="GetCredentialState",
            body_inner=pacs.credential_state(token=token),
        )
        return pacs.parse_credential_state(xml)

    def enable_credential(self, *, token: str, reason: str = "") -> None:
        """Send the ONVIF ``EnableCredential`` request to the Credential service."""
        self.call(
            service="credential",
            operation="EnableCredential",
            body_inner=pacs.enable_credential(token=token, reason=reason),
        )

    def disable_credential(self, *, token: str, reason: str = "") -> None:
        """Send the ONVIF ``DisableCredential`` request to the Credential service."""
        self.call(
            service="credential",
            operation="DisableCredential",
            body_inner=pacs.disable_credential(token=token, reason=reason),
        )

    def delete_credential(self, *, token: str) -> None:
        """Send the ONVIF ``DeleteCredential`` request to the Credential service."""
        self.call(
            service="credential",
            operation="DeleteCredential",
            body_inner=pacs.delete_credential(token=token),
        )

    def media2_create_profile(
        self, *, name: str, configurations: list[dict[str, str]] | None = None
    ) -> str:
        """Return the ONVIF ``CreateProfile`` result from the Media2 service, parsed by ``parsers.parse_created_token`` into ``str``."""
        xml = self.call(
            service="media2",
            operation="CreateProfile",
            body_inner=envelopes.media2_create_profile(name=name, configurations=configurations),
        )
        return parsers.parse_created_token(xml, tag="Token")

    def media2_delete_profile(self, *, token: str) -> None:
        """Send the ONVIF ``DeleteProfile`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="DeleteProfile",
            body_inner=envelopes.media2_delete_profile(token=token),
        )

    def media2_get_profiles(self, *, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetProfiles`` result from the Media2 service, parsed by ``parsers.parse_profiles`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="media2",
            operation="GetProfiles",
            body_inner=envelopes.media2_get_profiles(types=types),
        )
        return parsers.parse_profiles(xml)

    def media2_add_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]], name: str = ""
    ) -> None:
        """Send the ONVIF ``AddConfiguration`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="AddConfiguration",
            body_inner=envelopes.media2_add_configuration(
                profile_token=profile_token, configurations=configurations, name=name
            ),
        )

    def media2_remove_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]]
    ) -> None:
        """Send the ONVIF ``RemoveConfiguration`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="RemoveConfiguration",
            body_inner=envelopes.media2_remove_configuration(
                profile_token=profile_token, configurations=configurations
            ),
        )

    def media2_set_synchronization_point(self, *, profile_token: str) -> None:
        """Send the ONVIF ``SetSynchronizationPoint`` request to the Media2 service."""
        self.call(
            service="media2",
            operation="SetSynchronizationPoint",
            body_inner=envelopes.media2_set_synchronization_point(profile_token=profile_token),
        )

    def events_subscribe(
        self, *, consumer_address: str, topic_filter: str = "", termination_time: str = "PT60S"
    ) -> dict[str, Any]:
        """Return the ONVIF ``Subscribe`` result from the Events service, parsed by ``parsers.parse_create_pull_point`` into ``dict[str, Any]``."""
        xml = self.call(
            service="events",
            operation="Subscribe",
            body_inner=envelopes.events_subscribe(
                consumer_address=consumer_address,
                topic_filter=topic_filter,
                termination_time=termination_time,
            ),
        )
        return parsers.parse_create_pull_point(xml)

    def get_system_uris(self) -> dict[str, Any]:
        """Return the ONVIF ``GetSystemUris`` result from the Device service, parsed by ``parsers.parse_system_uris`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetSystemUris",
            body_inner=envelopes.device_get_system_uris(),
        )
        return parsers.parse_system_uris(xml)

    def get_geo_location(self) -> list[dict[str, float | None]]:
        """Return the ONVIF ``GetGeoLocation`` result from the Device service, parsed by ``parsers.parse_geo_location`` into ``list[dict[str, float | None]]``."""
        xml = self.call(
            service="device",
            operation="GetGeoLocation",
            body_inner=envelopes.device_get_geo_location(),
        )
        return parsers.parse_geo_location(xml)

    def set_geo_location(self, *, lon: float, lat: float, elevation: float = 0.0) -> None:
        """Send the ONVIF ``SetGeoLocation`` request to the Device service."""
        self.call(
            service="device",
            operation="SetGeoLocation",
            body_inner=envelopes.device_set_geo_location(lon=lon, lat=lat, elevation=elevation),
        )

    def get_wsdl_url(self) -> str:
        """Return the ONVIF ``GetWsdlUrl`` result from the Device service, parsed by ``parsers.parse_text_element`` into ``str``."""
        xml = self.call(
            service="device",
            operation="GetWsdlUrl",
            body_inner=envelopes.device_get_wsdl_url(),
        )
        return parsers.parse_text_element(xml, "Url")

    def get_zero_configuration(self) -> dict[str, Any]:
        """Return the ONVIF ``GetZeroConfiguration`` result from the Device service, parsed by ``parsers.parse_named_element`` into ``dict[str, Any]``."""
        xml = self.call(
            service="device",
            operation="GetZeroConfiguration",
            body_inner=envelopes.device_get_zero_configuration(),
        )
        return parsers.parse_named_element(xml, "ZeroConfiguration")

    def imaging_get_presets(self, *, video_source_token: str) -> list[dict[str, str]]:
        """Return the ONVIF ``GetPresets`` result from the Imaging service, parsed by ``parsers.parse_imaging_presets`` into ``list[dict[str, str]]``."""
        xml = self.call(
            service="imaging",
            operation="GetPresets",
            body_inner=envelopes.imaging_get_presets(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_presets(xml)

    def imaging_get_current_preset(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetCurrentPreset`` result from the Imaging service, parsed by ``parsers.parse_named_element`` into ``dict[str, Any]``."""
        xml = self.call(
            service="imaging",
            operation="GetCurrentPreset",
            body_inner=envelopes.imaging_get_current_preset(video_source_token=video_source_token),
        )
        return parsers.parse_named_element(xml, "Preset")

    def imaging_set_current_preset(self, *, video_source_token: str, preset_token: str) -> None:
        """Send the ONVIF ``SetCurrentPreset`` request to the Imaging service."""
        self.call(
            service="imaging",
            operation="SetCurrentPreset",
            body_inner=envelopes.imaging_set_current_preset(
                video_source_token=video_source_token, preset_token=preset_token
            ),
        )

    def ptz_get_compatible_configurations(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetCompatibleConfigurations`` result from the PTZ service, parsed by ``parsers.parse_ptz_configurations`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="ptz",
            operation="GetCompatibleConfigurations",
            body_inner=envelopes.ptz_get_compatible_configurations(profile_token=profile_token),
        )
        return parsers.parse_ptz_configurations(xml)

    def ptz_get_configuration_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the ONVIF ``GetConfigurationOptions`` result from the PTZ service, parsed by ``parsers.parse_named_element`` into ``dict[str, Any]``."""
        xml = self.call(
            service="ptz",
            operation="GetConfigurationOptions",
            body_inner=envelopes.ptz_get_configuration_options(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_named_element(xml, "PTZConfigurationOptions")

    def ptz_get_preset_tours(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the ONVIF ``GetPresetTours`` result from the PTZ service, parsed by ``parsers.parse_preset_tours`` into ``list[dict[str, Any]]``."""
        xml = self.call(
            service="ptz",
            operation="GetPresetTours",
            body_inner=envelopes.ptz_get_preset_tours(profile_token=profile_token),
        )
        return parsers.parse_preset_tours(xml)

    def ptz_operate_preset_tour(
        self, *, profile_token: str, preset_tour_token: str, operation: str
    ) -> None:
        """Send the ONVIF ``OperatePresetTour`` request to the PTZ service."""
        self.call(
            service="ptz",
            operation="OperatePresetTour",
            body_inner=envelopes.ptz_operate_preset_tour(
                profile_token=profile_token,
                preset_tour_token=preset_tour_token,
                operation=operation,
            ),
        )


def _snapshot_get(
    *,
    snapshot_uri: str,
    auth: httpx.Auth | None,
    timeout_s: float,
    verify_tls: bool,
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
    verify_tls: bool = True,
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
