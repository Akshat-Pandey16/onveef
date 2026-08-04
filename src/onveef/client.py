"""The synchronous ONVIF client.

:class:`OnvifClient` is assembled from the transport core in :mod:`onveef.transport` and
one mixin per ONVIF service in :mod:`onveef.ops`, so the operations for a given service
live in one navigable file rather than in a single 3000-line class.
"""

from __future__ import annotations

from onveef.ops.accesscontrol import AccessControlOperations
from onveef.ops.analytics import AnalyticsOperations
from onveef.ops.device import DeviceOperations
from onveef.ops.events import EventOperations, PullPointSubscription
from onveef.ops.imaging import ImagingOperations
from onveef.ops.media import MediaOperations
from onveef.ops.ptz import PtzOperations
from onveef.ops.recording import RecordingOperations
from onveef.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    OnvifCallResult,
    OnvifCredentials,
    OnvifEndpoint,
    SyncTransport,
    fetch_snapshot_bytes,
)

__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_USER_AGENT",
    "OnvifCallResult",
    "OnvifClient",
    "OnvifCredentials",
    "OnvifEndpoint",
    "PullPointSubscription",
    "SyncTransport",
    "fetch_snapshot_bytes",
]


class OnvifClient(
    DeviceOperations,
    MediaOperations,
    PtzOperations,
    ImagingOperations,
    EventOperations,
    AnalyticsOperations,
    RecordingOperations,
    AccessControlOperations,
):
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
        connect_timeout_s: Override the connect phase timeout.
        read_timeout_s: Override the read phase timeout (e.g. a longer read).
        verify_tls: Verify TLS certificates. Accepts ``False`` for cameras with self-signed
            certs, or a CA-bundle path / :class:`ssl.SSLContext` to pin one properly.
        rewrite_host: Re-point every address the device reports about itself (service
            XAddrs, subscription references, stream and snapshot URIs) at the host you
            actually connected to. Devices behind NAT, a port forward or a Docker bridge
            advertise their own unreachable address; leave this on unless you have a
            device whose services genuinely live on another host. See :mod:`onveef.urls`.
        breaker_key: Enable a per-client circuit breaker keyed by this id. Omit to disable.
        breaker_window_s: Sliding window over which failures are counted.
        breaker_threshold: Failures within the window that trip the breaker.
        breaker_open_s: How long the breaker stays open before a half-open probe.
        password_text: Always send the WS-Security password as plaintext ``PasswordText``.
        password_text_fallback: On a digest ``401``, retry once with ``PasswordText``. Some
            cheap firmware only accepts plaintext, but this sends **the password in the
            clear** on non-HTTPS transports, so it is off by default; opt in per device.
        ws_timestamp: Add a ``<wsu:Timestamp>`` to the security header (some strict devices).
        http_auth: HTTP transport auth to try when a device answers ``401`` with a
            ``WWW-Authenticate`` challenge — ``"auto"`` (Digest then Basic), ``"digest"``,
            ``"basic"``, or ``"none"``.
        retries: Automatic retries for transient failures on idempotent (read) operations.
        max_response_bytes: Hard cap on a single SOAP response body.
        user_agent: HTTP ``User-Agent`` header.
        transport: Custom :class:`httpx.BaseTransport` — e.g. ``httpx.MockTransport`` in
            tests, or a transport with bespoke connection limits.
        proxy: Proxy URL passed through to ``httpx``.
        http_client: Bring your own :class:`httpx.Client` (connection pooling shared with
            the rest of your application). You own its lifetime — ``close()`` leaves it open.
    """
