from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import Any

import httpx

from onveef import breaker, envelopes, pacs, parsers
from onveef.client import (
    _CONTENT_TYPES,
    _DEFAULT_DEVICE_PATH,
    _NOAUTH_OPERATIONS,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    OnvifCredentials,
    OnvifEndpoint,
    _is_idempotent,
    _iso8601_seconds,
    fetch_snapshot_bytes,
)
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


class AsyncOnvifClient:
    """An asyncio ONVIF client for a single device, mirroring :class:`~onveef.client.OnvifClient`.

    The quick way to connect is just host/port/username/password — service endpoints are
    discovered automatically on first use::

        async with AsyncOnvifClient("192.168.1.64", 80, "admin", "secret") as cam:
            print(await cam.get_device_information())
            for profile in await cam.get_profiles():
                print(await cam.get_stream_uri(profile_token=profile["token"]))

    For full control you may instead pass a pre-built ``endpoint=`` (and ``credentials=``);
    in that mode auto-discovery is off by default and you manage the service map yourself.

    Args mirror :class:`~onveef.client.OnvifClient` exactly; see its documentation for the
    meaning of every parameter.
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
        self._clock_lock = asyncio.Lock()
        self._read_override_s: float | None = None
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            verify=verify_tls,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )

    async def __aenter__(self) -> AsyncOnvifClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async HTTP connection pool."""
        await self._client.aclose()

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

    async def connect(self) -> AsyncOnvifClient:
        """Eagerly discover the device's services and return ``self`` for chaining."""
        await self._discover_once()
        return self

    async def _discover_once(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        try:
            services = await self.discover_services()
        except OnvifError:
            return
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
        self, *, url: str, content_type: str, envelope: str, auth: httpx.Auth | None
    ) -> tuple[int, str, str]:
        timeout = (
            self._timeout
            if self._read_override_s is None
            else httpx.Timeout(self._timeout, read=self._read_override_s)
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

    async def _post_soap(self, *, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        status, text, challenge = await self._raw_post(
            url=url, content_type=content_type, envelope=envelope, auth=None
        )
        if status == 401:
            auth = self._http_auth_for(challenge)
            if auth is not None:
                status, text, _ = await self._raw_post(
                    url=url, content_type=content_type, envelope=envelope, auth=auth
                )
        return status, text

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + random.random()
        return float(min(2.0, 0.25 * (2**attempt)) * jitter)

    async def _send_cycle(self, *, xaddr: str, operation: str, envelope: str) -> str:
        last_status = 0
        last_text = ""
        for ct in _CONTENT_TYPES:
            try:
                status, text = await self._post_soap(url=xaddr, envelope=envelope, content_type=ct)
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

    async def _call_raw(
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
                return await self._send_cycle(xaddr=xaddr, operation=operation, envelope=envelope)
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
    ) -> str:
        """Send one SOAP operation and return the raw response XML (advanced/escape hatch).

        Handles auth (WS-Security digest, clock-skew resync, optional plaintext fallback),
        content-type negotiation, retries, the circuit breaker, and fault classification.
        """
        await self._ensure(service)
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
                return await self._call_raw(
                    xaddr=xaddr, operation=operation, body_inner=body_inner, with_auth=False
                )
            except OnvifAuthError:
                if not self._credentials.configured:
                    raise
        try:
            return await self._call_raw(
                xaddr=xaddr, operation=operation, body_inner=body_inner, with_auth=True
            )
        except OnvifAuthError:
            if not self._credentials.configured:
                raise
            if not self._clock_synced:
                await self._sync_clock_offset()
                if self._clock_offset_s != 0.0:
                    try:
                        return await self._call_raw(
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
                    (
                        " over an unencrypted http:// connection"
                        if xaddr.startswith("http://")
                        else ""
                    ),
                )
                return await self._call_raw(
                    xaddr=xaddr,
                    operation=operation,
                    body_inner=body_inner,
                    with_auth=True,
                    password_text=True,
                )
            raise

    async def _sync_clock_offset(self) -> None:
        if self._clock_synced or self._clock_syncing:
            return
        async with self._clock_lock:
            if self._clock_synced or self._clock_syncing:
                return
            self._clock_syncing = True
            try:
                info = await self.get_system_date_time()
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

    async def _post_xml(self, *, url: str, envelope: str, operation: str) -> str:
        if self._breaker_open():
            raise OnvifTransportError(
                f"ONVIF call '{operation}' skipped: device circuit breaker open "
                "(recent transport failures)."
            )
        return await self._send_cycle(xaddr=url, operation=operation, envelope=envelope)

    async def _post_subscription(
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
            return await self._post_xml(url=subscription_url, envelope=build(), operation=operation)
        except OnvifAuthError:
            if self._clock_synced or not self._credentials.configured:
                raise
            await self._sync_clock_offset()
            if self._clock_offset_s == 0.0:
                raise
            return await self._post_xml(url=subscription_url, envelope=build(), operation=operation)

    async def get_device_information(self) -> dict[str, str]:
        """Return the device's manufacturer/model/firmware/serial/hardware information."""
        xml = await self.call(
            service="device",
            operation="GetDeviceInformation",
            body_inner=envelopes.device_get_information(),
        )
        return parsers.parse_device_information(xml)

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
        """Discover per-service XAddrs, preferring ``GetServices`` and falling back to caps."""
        try:
            services = await self.get_services()
            if services:
                return services
        except OnvifFaultError:
            services = {}
        return await self.get_capabilities()

    async def get_system_date_time(self) -> dict[str, Any]:
        """Return the device's system date/time (UTC and local)."""
        xml = await self.call(
            service="device",
            operation="GetSystemDateAndTime",
            body_inner=envelopes.device_get_system_date_time(),
        )
        return parsers.parse_system_datetime(xml)

    async def set_system_date_time(
        self,
        *,
        date_time_type: str = "Manual",
        daylight_savings: bool = False,
        timezone: str = "",
        utc_datetime: datetime | None = None,
    ) -> None:
        """Set the device's date/time mode, DST flag, timezone, and optional UTC value."""
        await self.call(
            service="device",
            operation="SetSystemDateAndTime",
            body_inner=envelopes.device_set_system_date_time(
                date_time_type=date_time_type,
                daylight_savings=daylight_savings,
                timezone=timezone,
                utc_datetime=utc_datetime,
            ),
        )

    async def get_hostname(self) -> str:
        """Return the device hostname."""
        xml = await self.call(
            service="device",
            operation="GetHostname",
            body_inner=envelopes.device_get_hostname(),
        )
        return parsers.parse_hostname(xml)

    async def set_hostname(self, name: str) -> None:
        """Set the device hostname to ``name``."""
        await self.call(
            service="device",
            operation="SetHostname",
            body_inner=envelopes.device_set_hostname(name),
        )

    async def get_network_interfaces(self) -> list[dict[str, Any]]:
        """Return the device's network interfaces."""
        xml = await self.call(
            service="device",
            operation="GetNetworkInterfaces",
            body_inner=envelopes.device_get_network_interfaces(),
        )
        return parsers.parse_network_interfaces(xml)

    async def get_users(self) -> list[dict[str, str]]:
        """Return the configured user accounts and their levels."""
        xml = await self.call(
            service="device",
            operation="GetUsers",
            body_inner=envelopes.device_get_users(),
        )
        return parsers.parse_users(xml)

    async def system_reboot(self) -> None:
        """Reboot the device."""
        await self.call(
            service="device",
            operation="SystemReboot",
            body_inner=envelopes.device_system_reboot(),
        )

    async def system_factory_default(self, *, hard: bool = False) -> None:
        """Reset the device to factory defaults (``hard`` for a full reset)."""
        await self.call(
            service="device",
            operation="SetSystemFactoryDefault",
            body_inner=envelopes.device_set_system_factory_default(hard=hard),
        )

    async def create_user(self, *, username: str, password: str, user_level: str) -> None:
        """Create a user account with the given username, password, and level."""
        await self.call(
            service="device",
            operation="CreateUsers",
            body_inner=envelopes.device_create_users(
                username=username, password=password, user_level=user_level
            ),
        )

    async def set_user(self, *, username: str, password: str, user_level: str) -> None:
        """Update an existing user's password and level."""
        await self.call(
            service="device",
            operation="SetUser",
            body_inner=envelopes.device_set_user(
                username=username, password=password, user_level=user_level
            ),
        )

    async def delete_users(self, *, usernames: list[str]) -> None:
        """Delete the named user accounts."""
        await self.call(
            service="device",
            operation="DeleteUsers",
            body_inner=envelopes.device_delete_users(usernames=usernames),
        )

    async def set_network_interface(
        self,
        *,
        token: str,
        enabled: bool,
        dhcp: bool,
        ipv4_address: str = "",
        prefix_length: int = 24,
        mtu: int | None = None,
    ) -> None:
        """Configure a network interface's enable/DHCP/IPv4/MTU settings."""
        await self.call(
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

    async def get_network_protocols(self) -> list[dict[str, Any]]:
        """Return the device's network protocols (HTTP/HTTPS/RTSP ports and enable flags)."""
        xml = await self.call(
            service="device",
            operation="GetNetworkProtocols",
            body_inner=envelopes.device_get_network_protocols(),
        )
        return parsers.parse_network_protocols(xml)

    async def set_network_protocols(self, *, protocols: list[dict[str, Any]]) -> None:
        """Set the device's network protocols."""
        await self.call(
            service="device",
            operation="SetNetworkProtocols",
            body_inner=envelopes.device_set_network_protocols(protocols=protocols),
        )

    async def get_network_default_gateway(self) -> dict[str, list[str]]:
        """Return the device's default gateway addresses."""
        xml = await self.call(
            service="device",
            operation="GetNetworkDefaultGateway",
            body_inner=envelopes.device_get_network_default_gateway(),
        )
        return parsers.parse_network_default_gateway(xml)

    async def set_network_default_gateway(self, *, ipv4_addresses: list[str]) -> None:
        """Set the device's IPv4 default gateway addresses."""
        await self.call(
            service="device",
            operation="SetNetworkDefaultGateway",
            body_inner=envelopes.device_set_network_default_gateway(ipv4_addresses=ipv4_addresses),
        )

    async def get_dns(self) -> dict[str, Any]:
        """Return the device's DNS configuration."""
        xml = await self.call(
            service="device",
            operation="GetDNS",
            body_inner=envelopes.device_get_dns(),
        )
        return parsers.parse_dns(xml)

    async def set_dns(
        self,
        *,
        from_dhcp: bool,
        ipv4_servers: list[str],
        search_domains: list[str],
    ) -> None:
        """Set the device's DNS servers and search domains."""
        await self.call(
            service="device",
            operation="SetDNS",
            body_inner=envelopes.device_set_dns(
                from_dhcp=from_dhcp,
                ipv4_servers=ipv4_servers,
                search_domains=search_domains,
            ),
        )

    async def get_ntp(self) -> dict[str, Any]:
        """Return the device's NTP configuration."""
        xml = await self.call(
            service="device",
            operation="GetNTP",
            body_inner=envelopes.device_get_ntp(),
        )
        return parsers.parse_ntp(xml)

    async def set_ntp(self, *, from_dhcp: bool, ipv4_servers: list[str]) -> None:
        """Set the device's NTP servers."""
        await self.call(
            service="device",
            operation="SetNTP",
            body_inner=envelopes.device_set_ntp(from_dhcp=from_dhcp, ipv4_servers=ipv4_servers),
        )

    async def get_scopes(self) -> list[dict[str, str]]:
        """Return the device's discovery scopes."""
        xml = await self.call(
            service="device",
            operation="GetScopes",
            body_inner=envelopes.device_get_scopes(),
        )
        return parsers.parse_scopes(xml)

    async def set_scopes(self, *, scopes: list[str]) -> None:
        """Replace the device's configurable discovery scopes."""
        await self.call(
            service="device",
            operation="SetScopes",
            body_inner=envelopes.device_set_scopes(scopes=scopes),
        )

    async def add_scopes(self, *, scopes: list[str]) -> None:
        """Add configurable discovery scopes."""
        await self.call(
            service="device",
            operation="AddScopes",
            body_inner=envelopes.device_add_scopes(scopes=scopes),
        )

    async def remove_scopes(self, *, scopes: list[str]) -> None:
        """Remove configurable discovery scopes."""
        await self.call(
            service="device",
            operation="RemoveScopes",
            body_inner=envelopes.device_remove_scopes(scopes=scopes),
        )

    async def get_geo_location(self) -> list[dict[str, float | None]]:
        """Return the device's geographic location entries."""
        xml = await self.call(
            service="device",
            operation="GetGeoLocation",
            body_inner=envelopes.device_get_geo_location(),
        )
        return parsers.parse_geo_location(xml)

    async def set_geo_location(self, *, lon: float, lat: float, elevation: float = 0.0) -> None:
        """Set the device's geographic location."""
        await self.call(
            service="device",
            operation="SetGeoLocation",
            body_inner=envelopes.device_set_geo_location(lon=lon, lat=lat, elevation=elevation),
        )

    async def get_system_log(self, *, log_type: str = "System") -> dict[str, str]:
        """Return a device system or access log."""
        xml = await self.call(
            service="device",
            operation="GetSystemLog",
            body_inner=envelopes.device_get_system_log(log_type=log_type),
        )
        return parsers.parse_system_log(xml)

    async def get_system_support_information(self) -> dict[str, str]:
        """Return the device's support information blob."""
        xml = await self.call(
            service="device",
            operation="GetSystemSupportInformation",
            body_inner=envelopes.device_get_system_support_information(),
        )
        return parsers.parse_support_information(xml)

    async def get_system_uris(self) -> dict[str, Any]:
        """Return the device's system log/support/backup download URIs."""
        xml = await self.call(
            service="device",
            operation="GetSystemUris",
            body_inner=envelopes.device_get_system_uris(),
        )
        return parsers.parse_system_uris(xml)

    async def get_certificates(self) -> list[dict[str, str]]:
        """Return the device's installed TLS certificates."""
        xml = await self.call(
            service="device",
            operation="GetCertificates",
            body_inner=envelopes.device_get_certificates(),
        )
        return parsers.parse_certificates(xml)

    async def get_dot1x_configurations(self) -> list[dict[str, Any]]:
        """Return the device's IEEE 802.1X configurations."""
        xml = await self.call(
            service="device",
            operation="GetDot1XConfigurations",
            body_inner=envelopes.device_get_dot1x_configurations(),
        )
        return parsers.parse_dot1x_configurations(xml)

    async def get_wsdl_url(self) -> str:
        """Return the device's WSDL base URL."""
        xml = await self.call(
            service="device",
            operation="GetWsdlUrl",
            body_inner=envelopes.device_get_wsdl_url(),
        )
        return parsers.parse_text_element(xml, "Url")

    async def get_zero_configuration(self) -> dict[str, Any]:
        """Return the device's zero-configuration (link-local) settings."""
        xml = await self.call(
            service="device",
            operation="GetZeroConfiguration",
            body_inner=envelopes.device_get_zero_configuration(),
        )
        return parsers.parse_named_element(xml, "ZeroConfiguration")

    async def get_service_capabilities(self, service: str) -> dict[str, Any]:
        """Return a service's capability flags (``media`` resolves to media/media2)."""
        resolved = service
        if service == "media":
            resolved, _ = await self._media_service()
        xml = await self.call(
            service=resolved,
            operation="GetServiceCapabilities",
            body_inner=envelopes.get_service_capabilities(resolved),
        )
        return parsers.parse_service_capabilities(xml)

    async def create_profile(self, *, name: str, token: str = "") -> str:
        """Create a media profile and return its token."""
        service, _ = await self._media_service()
        xml = await self.call(
            service=service,
            operation="CreateProfile",
            body_inner=envelopes.media_create_profile(name=name, token=token),
        )
        return parsers.parse_profile_create(xml) or token

    async def delete_profile(self, *, profile_token: str) -> None:
        """Delete a media profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="DeleteProfile",
            body_inner=envelopes.media_delete_profile(profile_token=profile_token),
        )

    async def add_video_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a video source configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddVideoSourceConfiguration",
            body_inner=envelopes.media_add_video_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def add_video_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a video encoder configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddVideoEncoderConfiguration",
            body_inner=envelopes.media_add_video_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_video_encoder_configuration(self, *, profile_token: str) -> None:
        """Remove the video encoder configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveVideoEncoderConfiguration",
            body_inner=envelopes.media_remove_video_encoder_configuration(
                profile_token=profile_token
            ),
        )

    async def add_ptz_configuration(self, *, profile_token: str, configuration_token: str) -> None:
        """Add a PTZ configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddPTZConfiguration",
            body_inner=envelopes.media_add_ptz_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_ptz_configuration(self, *, profile_token: str) -> None:
        """Remove the PTZ configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemovePTZConfiguration",
            body_inner=envelopes.media_remove_ptz_configuration(profile_token=profile_token),
        )

    async def add_audio_source_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add an audio source configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddAudioSourceConfiguration",
            body_inner=envelopes.media_add_audio_source_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def add_audio_encoder_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add an audio encoder configuration to a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="AddAudioEncoderConfiguration",
            body_inner=envelopes.media_add_audio_encoder_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_audio_encoder_configuration(self, *, profile_token: str) -> None:
        """Remove the audio encoder configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveAudioEncoderConfiguration",
            body_inner=envelopes.media_remove_audio_encoder_configuration(
                profile_token=profile_token
            ),
        )

    async def remove_audio_source_configuration(self, *, profile_token: str) -> None:
        """Remove the audio source configuration from a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="RemoveAudioSourceConfiguration",
            body_inner=envelopes.media_remove_audio_source_configuration(
                profile_token=profile_token
            ),
        )

    async def get_profiles(self) -> list[dict[str, Any]]:
        """Return the device's media profiles."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetProfiles",
            body_inner=envelopes.media_get_profiles(use_media2=use_media2),
        )
        return parsers.parse_profiles(xml)

    async def get_video_sources(self) -> list[dict[str, Any]]:
        """Return the device's video sources."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoSources",
            body_inner=envelopes.media_get_video_sources(use_media2=use_media2),
        )
        return parsers.parse_video_sources(xml)

    async def get_video_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video encoder configurations (preferring Media2)."""
        prefer_media2 = await self._has("media2")
        if prefer_media2:
            try:
                xml = await self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurations",
                    body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
                )
                configs = parsers.parse_video_encoder_configurations(xml)
                if configs:
                    return configs
            except OnvifCapabilityMissingError:
                pass
        if await self._has("media"):
            xml = await self.call(
                service="media",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=False),
            )
            return parsers.parse_video_encoder_configurations(xml)
        if prefer_media2:
            xml = await self.call(
                service="media2",
                operation="GetVideoEncoderConfigurations",
                body_inner=envelopes.media_get_video_encoder_configurations(use_media2=True),
            )
            return parsers.parse_video_encoder_configurations(xml)
        raise OnvifCapabilityMissingError("Device does not advertise a Media service.")

    async def get_stream_uri(
        self,
        *,
        profile_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
        protocol2: str = "RtspUnicast",
    ) -> str:
        """Return the RTSP stream URI for a profile."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
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

    async def get_snapshot_uri(self, *, profile_token: str) -> str:
        """Return the JPEG snapshot URI for a profile."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetSnapshotUri",
            body_inner=envelopes.media_get_snapshot_uri(
                profile_token=profile_token, use_media2=use_media2
            ),
        )
        return parsers.parse_snapshot_uri(xml)

    async def get_snapshot(self, *, profile_token: str) -> tuple[bytes, str]:
        """Fetch a JPEG snapshot for a profile as ``(image_bytes, content_type)``.

        Resolves the snapshot URI then downloads it with the client's credentials and TLS
        setting (HTTP Digest auth, falling back to Basic).
        """
        uri = await self.get_snapshot_uri(profile_token=profile_token)
        return fetch_snapshot_bytes(
            snapshot_uri=uri,
            credentials=self._credentials,
            timeout_s=self._timeout_s,
            verify_tls=self._verify_tls,
        )

    async def set_video_encoder_configuration(
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
        """Set a video encoder configuration via the legacy Media service."""
        if await self._has("media"):
            service = "media"
        else:
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration is only supported via the legacy Media service."
            )
        await self.call(
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

    async def get_video_encoder_options(
        self, *, configuration_token: str, profile_token: str = ""
    ) -> dict[str, Any]:
        """Return video encoder configuration options via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetVideoEncoderConfigurationOptions requires the legacy Media service."
            )
        xml = await self.call(
            service="media",
            operation="GetVideoEncoderConfigurationOptions",
            body_inner=envelopes.media_get_video_encoder_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    async def get_video_encoder_options_raw(
        self,
        *,
        configuration_token: str = "",
        profile_token: str = "",
        prefer: str = "auto",
    ) -> tuple[str, str]:
        """Return ``(service, raw_xml)`` of video encoder options from Media or Media2."""
        if prefer == "media2" and await self._has("media2"):
            return (
                "media2",
                await self.call(
                    service="media2",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media2_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if await self._has("media"):
            return (
                "media",
                await self.call(
                    service="media",
                    operation="GetVideoEncoderConfigurationOptions",
                    body_inner=envelopes.media_get_video_encoder_options(
                        configuration_token=configuration_token,
                        profile_token=profile_token,
                    ),
                ),
            )
        if await self._has("media2"):
            return (
                "media2",
                await self.call(
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

    async def set_video_encoder_configuration_media2(
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
        """Set a video encoder configuration via the Media2 service."""
        if not await self._has("media2"):
            raise OnvifCapabilityMissingError(
                "SetVideoEncoderConfiguration (Media2) requires the Media2 service."
            )
        await self.call(
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

    async def get_audio_encoder_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio encoder configurations."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetAudioEncoderConfigurations",
            body_inner=envelopes.media_get_audio_encoder_configurations(use_media2=use_media2),
        )
        return parsers.parse_audio_encoder_configurations(xml)

    async def set_audio_encoder_configuration(
        self,
        *,
        token: str,
        name: str,
        encoding: str,
        bitrate_kbps: int,
        sample_rate: int,
        force_persistence: bool = True,
    ) -> None:
        """Set an audio encoder configuration via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioEncoderConfiguration is only supported via the legacy Media service."
            )
        await self.call(
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

    async def get_audio_sources(self) -> list[dict[str, Any]]:
        """Return the device's audio sources (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioSources requires the legacy Media service.")
        xml = await self.call(
            service="media",
            operation="GetAudioSources",
            body_inner=envelopes.media_get_audio_sources(),
        )
        return parsers.parse_audio_sources(xml)

    async def get_audio_outputs(self) -> list[dict[str, Any]]:
        """Return the device's audio outputs (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError("GetAudioOutputs requires the legacy Media service.")
        xml = await self.call(
            service="media",
            operation="GetAudioOutputs",
            body_inner=envelopes.media_get_audio_outputs(),
        )
        return parsers.parse_audio_outputs(xml)

    async def get_audio_output_configurations(self) -> list[dict[str, Any]]:
        """Return the device's audio output configurations (legacy Media service)."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "GetAudioOutputConfigurations requires the legacy Media service."
            )
        xml = await self.call(
            service="media",
            operation="GetAudioOutputConfigurations",
            body_inner=envelopes.media_get_audio_output_configurations(),
        )
        return parsers.parse_audio_output_configurations(xml)

    async def set_audio_output_configuration(
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
        """Set an audio output configuration via the legacy Media service."""
        if not await self._has("media"):
            raise OnvifCapabilityMissingError(
                "SetAudioOutputConfiguration requires the legacy Media service."
            )
        await self.call(
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

    async def get_video_analytics_configurations(self) -> list[dict[str, Any]]:
        """Return the device's video analytics configurations."""
        service, use_media2 = await self._media_service()
        xml = await self.call(
            service=service,
            operation="GetVideoAnalyticsConfigurations",
            body_inner=envelopes.media_get_video_analytics_configurations(use_media2=use_media2),
        )
        return parsers.parse_video_analytics_configurations(xml)

    async def start_multicast_streaming(self, *, profile_token: str) -> None:
        """Start multicast streaming for a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="StartMulticastStreaming",
            body_inner=envelopes.media_start_multicast_streaming(profile_token=profile_token),
        )

    async def stop_multicast_streaming(self, *, profile_token: str) -> None:
        """Stop multicast streaming for a profile."""
        service, _ = await self._media_service()
        await self.call(
            service=service,
            operation="StopMulticastStreaming",
            body_inner=envelopes.media_stop_multicast_streaming(profile_token=profile_token),
        )

    async def get_osds(self, *, configuration_token: str = "") -> list[dict[str, Any]]:
        """Return the device's OSD entries (legacy Media service)."""
        await self._require_media1("GetOSDs")
        xml = await self.call(
            service="media",
            operation="GetOSDs",
            body_inner=envelopes.media_get_osds(configuration_token=configuration_token),
        )
        return parsers.parse_osds(xml)

    async def get_osd(self, *, osd_token: str) -> dict[str, Any]:
        """Return a single OSD entry (legacy Media service)."""
        await self._require_media1("GetOSD")
        xml = await self.call(
            service="media",
            operation="GetOSD",
            body_inner=envelopes.media_get_osd(osd_token=osd_token),
        )
        return parsers.parse_osd(xml)

    async def get_osd_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return OSD options for a video source configuration (legacy Media service)."""
        await self._require_media1("GetOSDOptions")
        xml = await self.call(
            service="media",
            operation="GetOSDOptions",
            body_inner=envelopes.media_get_osd_options(configuration_token=configuration_token),
        )
        return parsers.parse_osd_options(xml)

    async def create_osd(self, **kwargs: Any) -> str:
        """Create an OSD entry and return its token (legacy Media service)."""
        await self._require_media1("CreateOSD")
        xml = await self.call(
            service="media",
            operation="CreateOSD",
            body_inner=envelopes.media_create_osd(**kwargs),
        )
        return parsers.parse_created_token(xml, tag="OSDToken")

    async def set_osd(self, **kwargs: Any) -> None:
        """Update an OSD entry (legacy Media service)."""
        await self._require_media1("SetOSD")
        await self.call(
            service="media",
            operation="SetOSD",
            body_inner=envelopes.media_set_osd(**kwargs),
        )

    async def delete_osd(self, *, osd_token: str) -> None:
        """Delete an OSD entry (legacy Media service)."""
        await self._require_media1("DeleteOSD")
        await self.call(
            service="media",
            operation="DeleteOSD",
            body_inner=envelopes.media_delete_osd(osd_token=osd_token),
        )

    async def get_metadata_configurations(self) -> list[dict[str, Any]]:
        """Return the device's metadata configurations (legacy Media service)."""
        await self._require_media1("GetMetadataConfigurations")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfigurations",
            body_inner=envelopes.media_get_metadata_configurations(),
        )
        return parsers.parse_metadata_configurations(xml)

    async def get_metadata_configuration(self, *, configuration_token: str) -> dict[str, Any]:
        """Return a single metadata configuration (legacy Media service)."""
        await self._require_media1("GetMetadataConfiguration")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfiguration",
            body_inner=envelopes.media_get_metadata_configuration(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_metadata_configuration(xml)

    async def get_metadata_configuration_options(
        self, *, configuration_token: str = "", profile_token: str = ""
    ) -> dict[str, Any]:
        """Return metadata configuration options (legacy Media service)."""
        await self._require_media1("GetMetadataConfigurationOptions")
        xml = await self.call(
            service="media",
            operation="GetMetadataConfigurationOptions",
            body_inner=envelopes.media_get_metadata_configuration_options(
                configuration_token=configuration_token, profile_token=profile_token
            ),
        )
        return parsers.parse_video_encoder_options(xml)

    async def set_metadata_configuration(
        self,
        *,
        token: str,
        name: str,
        analytics: bool = True,
        ptz_status: bool = False,
        ptz_position: bool = False,
        use_count: int = 0,
    ) -> None:
        """Set a metadata configuration (legacy Media service)."""
        await self._require_media1("SetMetadataConfiguration")
        await self.call(
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

    async def add_metadata_configuration(
        self, *, profile_token: str, configuration_token: str
    ) -> None:
        """Add a metadata configuration to a profile (legacy Media service)."""
        await self._require_media1("AddMetadataConfiguration")
        await self.call(
            service="media",
            operation="AddMetadataConfiguration",
            body_inner=envelopes.media_add_metadata_configuration(
                profile_token=profile_token, configuration_token=configuration_token
            ),
        )

    async def remove_metadata_configuration(self, *, profile_token: str) -> None:
        """Remove the metadata configuration from a profile (legacy Media service)."""
        await self._require_media1("RemoveMetadataConfiguration")
        await self.call(
            service="media",
            operation="RemoveMetadataConfiguration",
            body_inner=envelopes.media_remove_metadata_configuration(profile_token=profile_token),
        )

    async def media2_create_profile(
        self, *, name: str, configurations: list[dict[str, str]] | None = None
    ) -> str:
        """Create a Media2 profile and return its token."""
        xml = await self.call(
            service="media2",
            operation="CreateProfile",
            body_inner=envelopes.media2_create_profile(name=name, configurations=configurations),
        )
        return parsers.parse_created_token(xml, tag="Token")

    async def media2_delete_profile(self, *, token: str) -> None:
        """Delete a Media2 profile."""
        await self.call(
            service="media2",
            operation="DeleteProfile",
            body_inner=envelopes.media2_delete_profile(token=token),
        )

    async def media2_get_profiles(self, *, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Return Media2 profiles, optionally filtered by configuration ``types``."""
        xml = await self.call(
            service="media2",
            operation="GetProfiles",
            body_inner=envelopes.media2_get_profiles(types=types),
        )
        return parsers.parse_profiles(xml)

    async def media2_add_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]], name: str = ""
    ) -> None:
        """Add configurations to a Media2 profile."""
        await self.call(
            service="media2",
            operation="AddConfiguration",
            body_inner=envelopes.media2_add_configuration(
                profile_token=profile_token, configurations=configurations, name=name
            ),
        )

    async def media2_remove_configuration(
        self, *, profile_token: str, configurations: list[dict[str, str]]
    ) -> None:
        """Remove configurations from a Media2 profile."""
        await self.call(
            service="media2",
            operation="RemoveConfiguration",
            body_inner=envelopes.media2_remove_configuration(
                profile_token=profile_token, configurations=configurations
            ),
        )

    async def media2_set_synchronization_point(self, *, profile_token: str) -> None:
        """Request a Media2 synchronization point for a profile."""
        await self.call(
            service="media2",
            operation="SetSynchronizationPoint",
            body_inner=envelopes.media2_set_synchronization_point(profile_token=profile_token),
        )

    async def ptz_get_nodes(self) -> list[dict[str, Any]]:
        """Return the device's PTZ nodes."""
        xml = await self.call(
            service="ptz",
            operation="GetNodes",
            body_inner=envelopes.ptz_get_nodes(),
        )
        return parsers.parse_ptz_nodes(xml)

    async def ptz_get_status(self, *, profile_token: str) -> dict[str, Any]:
        """Return the PTZ status for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetStatus",
            body_inner=envelopes.ptz_get_status(profile_token=profile_token),
        )
        return parsers.parse_ptz_status(xml)

    async def ptz_continuous_move(
        self,
        *,
        profile_token: str,
        pan: float | None,
        tilt: float | None,
        zoom: float | None,
        timeout: str = "",
    ) -> None:
        """Start a continuous PTZ move with the given pan/tilt/zoom velocities."""
        await self.call(
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

    async def ptz_absolute_move(
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
        """Move PTZ to an absolute pan/tilt/zoom position, optionally at a given speed."""
        await self.call(
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

    async def ptz_relative_move(
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
        """Move PTZ by a relative pan/tilt/zoom offset, optionally at a given speed."""
        await self.call(
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

    async def ptz_stop(
        self, *, profile_token: str, pan_tilt: bool = True, zoom: bool = True
    ) -> None:
        """Stop PTZ pan/tilt and/or zoom motion for a profile."""
        await self.call(
            service="ptz",
            operation="Stop",
            body_inner=envelopes.ptz_stop(
                profile_token=profile_token, pan_tilt=pan_tilt, zoom=zoom
            ),
        )

    async def ptz_get_presets(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the PTZ presets for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetPresets",
            body_inner=envelopes.ptz_get_presets(profile_token=profile_token),
        )
        return parsers.parse_ptz_presets(xml)

    async def ptz_set_preset(
        self,
        *,
        profile_token: str,
        preset_name: str = "",
        preset_token: str = "",
    ) -> str:
        """Create or update a PTZ preset and return its token."""
        xml = await self.call(
            service="ptz",
            operation="SetPreset",
            body_inner=envelopes.ptz_set_preset(
                profile_token=profile_token,
                preset_name=preset_name,
                preset_token=preset_token,
            ),
        )
        return parsers.parse_set_preset_token(xml) or preset_token

    async def ptz_remove_preset(self, *, profile_token: str, preset_token: str) -> None:
        """Remove a PTZ preset."""
        await self.call(
            service="ptz",
            operation="RemovePreset",
            body_inner=envelopes.ptz_remove_preset(
                profile_token=profile_token, preset_token=preset_token
            ),
        )

    async def ptz_goto_preset(
        self,
        *,
        profile_token: str,
        preset_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Move PTZ to a stored preset, optionally at a given speed."""
        await self.call(
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

    async def ptz_set_home_position(self, *, profile_token: str) -> None:
        """Store the current PTZ position as the home position."""
        await self.call(
            service="ptz",
            operation="SetHomePosition",
            body_inner=envelopes.ptz_set_home_position(profile_token=profile_token),
        )

    async def ptz_goto_home_position(
        self,
        *,
        profile_token: str,
        speed_pan: float | None = None,
        speed_tilt: float | None = None,
        speed_zoom: float | None = None,
    ) -> None:
        """Move PTZ to the home position, optionally at a given speed."""
        await self.call(
            service="ptz",
            operation="GotoHomePosition",
            body_inner=envelopes.ptz_goto_home_position(
                profile_token=profile_token,
                speed_pan=speed_pan,
                speed_tilt=speed_tilt,
                speed_zoom=speed_zoom,
            ),
        )

    async def ptz_get_configurations(self) -> list[dict[str, Any]]:
        """Return the device's PTZ configurations."""
        xml = await self.call(
            service="ptz",
            operation="GetConfigurations",
            body_inner=envelopes.ptz_get_configurations(),
        )
        return parsers.parse_ptz_configurations(xml)

    async def ptz_get_compatible_configurations(
        self, *, profile_token: str
    ) -> list[dict[str, Any]]:
        """Return PTZ configurations compatible with a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetCompatibleConfigurations",
            body_inner=envelopes.ptz_get_compatible_configurations(profile_token=profile_token),
        )
        return parsers.parse_ptz_configurations(xml)

    async def ptz_get_configuration_options(self, *, configuration_token: str) -> dict[str, Any]:
        """Return the option ranges for a PTZ configuration."""
        xml = await self.call(
            service="ptz",
            operation="GetConfigurationOptions",
            body_inner=envelopes.ptz_get_configuration_options(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_named_element(xml, "PTZConfigurationOptions")

    async def ptz_send_auxiliary_command(self, *, profile_token: str, auxiliary_data: str) -> None:
        """Send a PTZ auxiliary command (e.g. a wiper or IR light)."""
        await self.call(
            service="ptz",
            operation="SendAuxiliaryCommand",
            body_inner=envelopes.ptz_send_auxiliary_command(
                profile_token=profile_token, auxiliary_data=auxiliary_data
            ),
        )

    async def ptz_get_preset_tours(self, *, profile_token: str) -> list[dict[str, Any]]:
        """Return the PTZ preset tours for a profile."""
        xml = await self.call(
            service="ptz",
            operation="GetPresetTours",
            body_inner=envelopes.ptz_get_preset_tours(profile_token=profile_token),
        )
        return parsers.parse_preset_tours(xml)

    async def ptz_operate_preset_tour(
        self, *, profile_token: str, preset_tour_token: str, operation: str
    ) -> None:
        """Start/stop/pause a PTZ preset tour."""
        await self.call(
            service="ptz",
            operation="OperatePresetTour",
            body_inner=envelopes.ptz_operate_preset_tour(
                profile_token=profile_token,
                preset_tour_token=preset_tour_token,
                operation=operation,
            ),
        )

    async def imaging_get_settings(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the imaging settings for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetImagingSettings",
            body_inner=envelopes.imaging_get_settings(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_settings(xml)

    async def imaging_get_options(self, *, video_source_token: str) -> str:
        """Return the raw imaging options XML for a video source."""
        return await self.call(
            service="imaging",
            operation="GetOptions",
            body_inner=envelopes.imaging_get_options(video_source_token=video_source_token),
        )

    async def imaging_get_options_parsed(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the parsed imaging options for a video source."""
        xml = await self.imaging_get_options(video_source_token=video_source_token)
        return parsers.parse_imaging_options(xml)

    async def imaging_get_status(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the imaging status (e.g. focus) for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetStatus",
            body_inner=envelopes.imaging_get_status(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_status(xml)

    async def imaging_set_settings(self, *, video_source_token: str, **kwargs: Any) -> None:
        """Set imaging settings for a video source (brightness, contrast, focus, ...)."""
        body = envelopes.imaging_set_settings(video_source_token=video_source_token, **kwargs)
        await self.call(
            service="imaging",
            operation="SetImagingSettings",
            body_inner=body,
        )

    async def imaging_move(
        self,
        *,
        video_source_token: str,
        focus_continuous: float | None = None,
        focus_absolute: float | None = None,
        focus_relative: float | None = None,
        speed: float | None = None,
    ) -> None:
        """Drive the imaging (focus) actuator continuously/absolutely/relatively."""
        await self.call(
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

    async def imaging_stop(self, *, video_source_token: str) -> None:
        """Stop imaging (focus) movement for a video source."""
        await self.call(
            service="imaging",
            operation="Stop",
            body_inner=envelopes.imaging_stop(video_source_token=video_source_token),
        )

    async def imaging_get_presets(self, *, video_source_token: str) -> list[dict[str, str]]:
        """Return the imaging presets for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetPresets",
            body_inner=envelopes.imaging_get_presets(video_source_token=video_source_token),
        )
        return parsers.parse_imaging_presets(xml)

    async def imaging_get_current_preset(self, *, video_source_token: str) -> dict[str, Any]:
        """Return the current imaging preset for a video source."""
        xml = await self.call(
            service="imaging",
            operation="GetCurrentPreset",
            body_inner=envelopes.imaging_get_current_preset(video_source_token=video_source_token),
        )
        return parsers.parse_named_element(xml, "Preset")

    async def imaging_set_current_preset(
        self, *, video_source_token: str, preset_token: str
    ) -> None:
        """Apply an imaging preset to a video source."""
        await self.call(
            service="imaging",
            operation="SetCurrentPreset",
            body_inner=envelopes.imaging_set_current_preset(
                video_source_token=video_source_token, preset_token=preset_token
            ),
        )

    async def analytics_get_supported_rules(
        self, *, configuration_token: str
    ) -> list[dict[str, Any]]:
        """Return the analytics rules supported by a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetSupportedRules",
            body_inner=envelopes.analytics_get_supported_rules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_rules(xml)

    async def analytics_get_rules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the analytics rules configured on a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetRules",
            body_inner=envelopes.analytics_get_rules(configuration_token=configuration_token),
        )
        return parsers.parse_rules(xml)

    async def analytics_get_supported_modules(
        self, *, configuration_token: str
    ) -> list[dict[str, Any]]:
        """Return the analytics modules supported by a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetSupportedAnalyticsModules",
            body_inner=envelopes.analytics_get_supported_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

    async def analytics_get_modules(self, *, configuration_token: str) -> list[dict[str, Any]]:
        """Return the analytics modules configured on a configuration."""
        xml = await self.call(
            service="analytics",
            operation="GetAnalyticsModules",
            body_inner=envelopes.analytics_get_analytics_modules(
                configuration_token=configuration_token
            ),
        )
        return parsers.parse_analytics_modules(xml)

    async def create_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Create analytics modules on a configuration."""
        await self.call(
            service="analytics",
            operation="CreateAnalyticsModules",
            body_inner=envelopes.analytics_create_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    async def modify_analytics_modules(
        self, *, configuration_token: str, modules: list[dict[str, Any]]
    ) -> None:
        """Modify analytics modules on a configuration."""
        await self.call(
            service="analytics",
            operation="ModifyAnalyticsModules",
            body_inner=envelopes.analytics_modify_analytics_modules(
                configuration_token=configuration_token, modules=modules
            ),
        )

    async def delete_analytics_modules(self, *, configuration_token: str, names: list[str]) -> None:
        """Delete named analytics modules from a configuration."""
        await self.call(
            service="analytics",
            operation="DeleteAnalyticsModules",
            body_inner=envelopes.analytics_delete_analytics_modules(
                configuration_token=configuration_token, names=names
            ),
        )

    async def create_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Create analytics rules on a configuration."""
        await self.call(
            service="analytics",
            operation="CreateRules",
            body_inner=envelopes.analytics_create_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    async def modify_rules(self, *, configuration_token: str, rules: list[dict[str, Any]]) -> None:
        """Modify analytics rules on a configuration."""
        await self.call(
            service="analytics",
            operation="ModifyRules",
            body_inner=envelopes.analytics_modify_rules(
                configuration_token=configuration_token, rules=rules
            ),
        )

    async def delete_rules(self, *, configuration_token: str, names: list[str]) -> None:
        """Delete named analytics rules from a configuration."""
        await self.call(
            service="analytics",
            operation="DeleteRules",
            body_inner=envelopes.analytics_delete_rules(
                configuration_token=configuration_token, names=names
            ),
        )

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
        """Create a pull-point subscription and return its manager URL/times."""
        xml = await self.call(
            service="events",
            operation="CreatePullPointSubscription",
            body_inner=envelopes.events_create_pull_point_subscription(
                termination_time=termination_time, topic_filter=topic_filter
            ),
        )
        return parsers.parse_create_pull_point(xml)

    async def events_subscribe(
        self, *, consumer_address: str, topic_filter: str = "", termination_time: str = "PT60S"
    ) -> dict[str, Any]:
        """Create a base notification (push) subscription to ``consumer_address``."""
        xml = await self.call(
            service="events",
            operation="Subscribe",
            body_inner=envelopes.events_subscribe(
                consumer_address=consumer_address,
                topic_filter=topic_filter,
                termination_time=termination_time,
            ),
        )
        return parsers.parse_create_pull_point(xml)

    async def events_pull_messages(
        self,
        *,
        subscription_url: str,
        timeout: str = "PT5S",
        message_limit: int = 20,
    ) -> dict[str, Any]:
        """Long-poll a pull-point subscription for notification messages."""
        prev_override = self._read_override_s
        self._read_override_s = _iso8601_seconds(timeout, 5.0) + 5.0
        try:
            xml = await self._post_subscription(
                subscription_url=subscription_url,
                body=envelopes.events_pull_messages(timeout=timeout, message_limit=message_limit),
                wsa_action=(
                    "http://www.onvif.org/ver10/events/wsdl/"
                    "PullPointSubscription/PullMessagesRequest"
                ),
                operation="PullMessages",
            )
        finally:
            self._read_override_s = prev_override
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

    async def get_recordings(self) -> list[dict[str, Any]]:
        """Return the device's recordings (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordings",
            body_inner=envelopes.recording_get_recordings(),
        )
        return parsers.parse_recordings(xml)

    async def create_recording(
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
        """Create a recording and return its token (Profile G)."""
        xml = await self.call(
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

    async def delete_recording(self, *, recording_token: str) -> None:
        """Delete a recording (Profile G)."""
        await self.call(
            service="recording",
            operation="DeleteRecording",
            body_inner=envelopes.recording_delete_recording(recording_token=recording_token),
        )

    async def get_recording_configuration(self, *, recording_token: str) -> dict[str, Any]:
        """Return a recording's configuration (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordingConfiguration",
            body_inner=envelopes.recording_get_recording_configuration(
                recording_token=recording_token
            ),
        )
        return parsers.parse_recording_configuration(xml)

    async def set_recording_configuration(
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
        """Set a recording's configuration (Profile G)."""
        await self.call(
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

    async def get_recording_jobs(self) -> list[dict[str, Any]]:
        """Return the device's recording jobs (Profile G)."""
        xml = await self.call(
            service="recording",
            operation="GetRecordingJobs",
            body_inner=envelopes.recording_get_recording_jobs(),
        )
        return parsers.parse_recording_jobs(xml)

    async def create_recording_job(
        self,
        *,
        recording_token: str,
        mode: str = "Active",
        priority: int = 10,
        source_token: str = "",
        source_type: str = "",
    ) -> str:
        """Create a recording job and return its token (Profile G)."""
        xml = await self.call(
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

    async def delete_recording_job(self, *, job_token: str) -> None:
        """Delete a recording job (Profile G)."""
        await self.call(
            service="recording",
            operation="DeleteRecordingJob",
            body_inner=envelopes.recording_delete_recording_job(job_token=job_token),
        )

    async def set_recording_job_mode(self, *, job_token: str, mode: str) -> None:
        """Set a recording job's mode (Profile G)."""
        await self.call(
            service="recording",
            operation="SetRecordingJobMode",
            body_inner=envelopes.recording_set_recording_job_mode(job_token=job_token, mode=mode),
        )

    async def get_recording_summary(self) -> dict[str, Any]:
        """Return the recording search summary (Profile G)."""
        xml = await self.call(
            service="search",
            operation="GetRecordingSummary",
            body_inner=envelopes.search_get_recording_summary(),
        )
        return parsers.parse_recording_summary(xml)

    async def find_recordings(
        self,
        *,
        included_sources: list[str] | None = None,
        included_recordings: list[str] | None = None,
        max_matches: int | None = None,
        keep_alive: str = "PT60S",
    ) -> str:
        """Start a recording search and return its search token (Profile G)."""
        xml = await self.call(
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

    async def get_recording_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a recording search (Profile G)."""
        xml = await self.call(
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

    async def find_events(
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
        """Start an event search and return its search token (Profile G)."""
        xml = await self.call(
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

    async def get_event_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for an event search (Profile G)."""
        xml = await self.call(
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

    async def find_ptz_position(
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
        """Start a PTZ-position search and return its search token (Profile G)."""
        xml = await self.call(
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

    async def get_ptz_position_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a PTZ-position search (Profile G)."""
        xml = await self.call(
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

    async def find_metadata(
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
        """Start a metadata search and return its search token (Profile G)."""
        xml = await self.call(
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

    async def get_metadata_search_results(
        self,
        *,
        search_token: str,
        min_results: int | None = None,
        max_results: int | None = None,
        wait_time: str = "PT5S",
    ) -> dict[str, Any]:
        """Fetch results for a metadata search (Profile G)."""
        xml = await self.call(
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

    async def end_search(self, *, search_token: str) -> None:
        """End an in-progress search (Profile G)."""
        await self.call(
            service="search",
            operation="EndSearch",
            body_inner=envelopes.search_end_search(search_token=search_token),
        )

    async def get_replay_uri(
        self,
        *,
        recording_token: str,
        stream: str = "RTP-Unicast",
        protocol: str = "RTSP",
    ) -> str:
        """Return the replay (RTSP) URI for a recording (Profile G)."""
        xml = await self.call(
            service="replay",
            operation="GetReplayUri",
            body_inner=envelopes.replay_get_replay_uri(
                recording_token=recording_token, stream=stream, protocol=protocol
            ),
        )
        return parsers.parse_stream_uri(xml)

    async def get_replay_configuration(self) -> dict[str, Any]:
        """Return the replay service configuration (Profile G)."""
        xml = await self.call(
            service="replay",
            operation="GetReplayConfiguration",
            body_inner=envelopes.replay_get_replay_configuration(),
        )
        return parsers.parse_replay_configuration(xml)

    async def set_replay_configuration(self, *, session_timeout: str = "PT60S") -> None:
        """Set the replay service session timeout (Profile G)."""
        await self.call(
            service="replay",
            operation="SetReplayConfiguration",
            body_inner=envelopes.replay_set_replay_configuration(session_timeout=session_timeout),
        )

    async def get_relay_outputs(self) -> list[dict[str, Any]]:
        """Return the device's relay outputs."""
        service, use_deviceio = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetRelayOutputs",
            body_inner=envelopes.device_get_relay_outputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_relay_outputs(xml)

    async def set_relay_output_state(self, *, token: str, logical_state: str) -> None:
        """Set a relay output's logical state (active/inactive)."""
        service, use_deviceio = await self._relay_service()
        await self.call(
            service=service,
            operation="SetRelayOutputState",
            body_inner=envelopes.device_set_relay_output_state(
                token=token, logical_state=logical_state, use_deviceio=use_deviceio
            ),
        )

    async def set_relay_output_settings(
        self,
        *,
        token: str,
        mode: str,
        delay_time: str,
        idle_state: str,
    ) -> None:
        """Set a relay output's mode, delay time, and idle state."""
        service, use_deviceio = await self._relay_service()
        await self.call(
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

    async def get_relay_output_options(self, *, token: str = "") -> list[dict[str, Any]]:
        """Return the option ranges for relay outputs."""
        service, _ = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetRelayOutputOptions",
            body_inner=envelopes.device_get_relay_output_options(token=token),
        )
        return parsers.parse_relay_output_options(xml)

    async def get_digital_inputs(self) -> list[dict[str, Any]]:
        """Return the device's digital inputs."""
        service, use_deviceio = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetDigitalInputs",
            body_inner=envelopes.device_get_digital_inputs(use_deviceio=use_deviceio),
        )
        return parsers.parse_digital_inputs(xml)

    async def get_serial_ports(self) -> list[dict[str, str]]:
        """Return the device's serial ports."""
        service, _ = await self._relay_service()
        xml = await self.call(
            service=service,
            operation="GetSerialPorts",
            body_inner=envelopes.device_get_serial_ports(),
        )
        return parsers.parse_serial_ports(xml)

    async def get_access_point_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return access points and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAccessPointInfoList",
            body_inner=pacs.access_point_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_access_point_info_list(xml)

    async def get_access_point_state(self, *, token: str) -> dict[str, Any]:
        """Return an access point's state (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAccessPointState",
            body_inner=pacs.access_point_state(token=token),
        )
        return pacs.parse_access_point_state(xml)

    async def enable_access_point(self, *, token: str) -> None:
        """Enable an access point (Profile A/C)."""
        await self.call(
            service="accesscontrol",
            operation="EnableAccessPoint",
            body_inner=pacs.enable_access_point(token=token),
        )

    async def disable_access_point(self, *, token: str) -> None:
        """Disable an access point (Profile A/C)."""
        await self.call(
            service="accesscontrol",
            operation="DisableAccessPoint",
            body_inner=pacs.disable_access_point(token=token),
        )

    async def get_area_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return areas and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="accesscontrol",
            operation="GetAreaInfoList",
            body_inner=pacs.area_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_area_info_list(xml)

    async def get_door_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return doors and a pagination reference (Profile A/C)."""
        xml = await self.call(
            service="doorcontrol",
            operation="GetDoorInfoList",
            body_inner=pacs.door_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_door_info_list(xml)

    async def get_door_state(self, *, token: str) -> dict[str, Any]:
        """Return a door's state (Profile A/C)."""
        xml = await self.call(
            service="doorcontrol",
            operation="GetDoorState",
            body_inner=pacs.door_state(token=token),
        )
        return pacs.parse_door_state(xml)

    async def door_command(self, command: str, *, token: str) -> None:
        """Send an arbitrary door command (e.g. ``AccessDoor``) to a door (Profile A/C)."""
        await self.call(
            service="doorcontrol",
            operation=command,
            body_inner=pacs.door_action(command, token=token),
        )

    async def access_door(self, *, token: str) -> None:
        """Momentarily grant access at a door (Profile A/C)."""
        await self.door_command("AccessDoor", token=token)

    async def lock_door(self, *, token: str) -> None:
        """Lock a door (Profile A/C)."""
        await self.door_command("LockDoor", token=token)

    async def unlock_door(self, *, token: str) -> None:
        """Unlock a door (Profile A/C)."""
        await self.door_command("UnlockDoor", token=token)

    async def get_credential_info_list(
        self, *, limit: int | None = None, start_reference: str = ""
    ) -> dict[str, Any]:
        """Return credentials and a pagination reference (Profile C)."""
        xml = await self.call(
            service="credential",
            operation="GetCredentialInfoList",
            body_inner=pacs.credential_info_list(limit=limit, start_reference=start_reference),
        )
        return pacs.parse_credential_info_list(xml)

    async def get_credential_state(self, *, token: str) -> dict[str, Any]:
        """Return a credential's state (Profile C)."""
        xml = await self.call(
            service="credential",
            operation="GetCredentialState",
            body_inner=pacs.credential_state(token=token),
        )
        return pacs.parse_credential_state(xml)

    async def enable_credential(self, *, token: str, reason: str = "") -> None:
        """Enable a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="EnableCredential",
            body_inner=pacs.enable_credential(token=token, reason=reason),
        )

    async def disable_credential(self, *, token: str, reason: str = "") -> None:
        """Disable a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="DisableCredential",
            body_inner=pacs.disable_credential(token=token, reason=reason),
        )

    async def delete_credential(self, *, token: str) -> None:
        """Delete a credential (Profile C)."""
        await self.call(
            service="credential",
            operation="DeleteCredential",
            body_inner=pacs.delete_credential(token=token),
        )
