"""WS-Discovery multicast probing for ONVIF devices on the local network."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from onveef.parsers import child_text, find_all_local, find_local, parse_xml

logger = logging.getLogger("onveef")

WS_DISCOVERY_ADDRESS = "239.255.255.250"
WS_DISCOVERY_ADDRESS_IPV6 = "ff02::c"
WS_DISCOVERY_PORT = 3702
_MULTICAST_TO = "urn:schemas-xmlsoap-org:ws:2005:04:discovery"
_PROBE_ACTION = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe"

DEFAULT_TYPES = "dn:NetworkVideoTransmitter tds:Device"
"""Match cameras, NVRs and access-control devices. Pass ``""`` to match every device."""

_DEFAULT_TYPES = DEFAULT_TYPES
_DEFAULT_PROBES = 3

_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
    "<s:Header>"
    "<a:MessageID>{message_id}</a:MessageID>"
    f'<a:To s:mustUnderstand="1">{_MULTICAST_TO}</a:To>'
    f'<a:Action s:mustUnderstand="1">{_PROBE_ACTION}</a:Action>'
    "</s:Header>"
    "<s:Body>"
    '<d:Probe xmlns:dn="http://www.onvif.org/ver10/network/wsdl" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
    "<d:Types>{types}</d:Types><d:Scopes/>"
    "</d:Probe>"
    "</s:Body></s:Envelope>"
)


@dataclass(slots=True)
class DiscoveredDevice:
    address: str
    endpoint_reference: str = ""
    xaddrs: list[str] = field(default_factory=list)
    types: str = ""
    scopes: list[str] = field(default_factory=list)
    name: str = ""
    hardware: str = ""
    location: str = ""
    metadata_version: str = ""

    @property
    def device_service(self) -> str:
        return self.xaddrs[0] if self.xaddrs else ""


def build_probe(*, message_id: str, types: str = DEFAULT_TYPES) -> str:
    """Build a WS-Discovery ``Probe`` envelope.

    Defaults to the same device types :func:`discover` probes for, so driving the multicast
    yourself finds exactly what the built-in helper would.
    """
    return _ENVELOPE.format(message_id=message_id, types=types)


def local_ipv4_addresses() -> list[str]:
    """Best-effort list of this host's routable IPv4 addresses, for per-interface probing.

    A single ``0.0.0.0`` bind sends the probe out one kernel-chosen interface, which finds
    nothing on a multi-homed host — and any machine running Docker is multi-homed. This
    resolves the host's own names and the default route's source address without pulling in
    a dependency; it is a best effort, not a complete interface enumeration.
    """
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(str(info[4][0]))
    except (OSError, UnicodeError):
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 53))
        found.add(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    return sorted(a for a in found if a and not a.startswith("127."))


def _scope_value(scopes: list[str], segment: str) -> str:
    marker = f"/{segment}/"
    for scope in scopes:
        idx = scope.find(marker)
        if idx != -1:
            return scope[idx + len(marker) :].strip("/")
    return ""


def parse_probe_matches(xml: str) -> list[DiscoveredDevice]:
    root = parse_xml(xml)
    if root is None:
        return []
    out: list[DiscoveredDevice] = []
    for match in find_all_local(root, "ProbeMatch"):
        ref = find_local(match, "EndpointReference")
        endpoint = child_text(ref, "Address") if ref is not None else ""
        xaddrs = child_text(match, "XAddrs").split()
        scopes = child_text(match, "Scopes").split()
        out.append(
            DiscoveredDevice(
                address=xaddrs[0] if xaddrs else "",
                endpoint_reference=endpoint,
                xaddrs=xaddrs,
                types=child_text(match, "Types"),
                scopes=scopes,
                name=_scope_value(scopes, "name"),
                hardware=_scope_value(scopes, "hardware"),
                location=_scope_value(scopes, "location"),
                metadata_version=child_text(match, "MetadataVersion"),
            )
        )
    return out


def _collect(results: dict[str, DiscoveredDevice], data: bytes, sender_ip: str) -> None:
    for device in parse_probe_matches(data.decode("utf-8", errors="replace")):
        if not device.address:
            device.address = sender_ip
        key = device.endpoint_reference or device.address or sender_ip
        results[key] = device


def _probe_payloads(types: str, probes: int) -> list[bytes]:
    """Build ``probes`` distinct Probe envelopes (each needs its own MessageID)."""
    return [
        build_probe(message_id=f"urn:uuid:{uuid.uuid4()}", types=types).encode("utf-8")
        for _ in range(max(1, probes))
    ]


def _open_socket(family: int, bind_ip: str, ttl: int) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, ttl)
            sock.bind((bind_ip or "::", 0))
        else:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            if bind_ip and bind_ip != "0.0.0.0":
                sock.setsockopt(
                    socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(bind_ip)
                )
            sock.bind((bind_ip or "0.0.0.0", 0))
    except OSError:
        sock.close()
        raise
    return sock


def _listen(
    sock: socket.socket,
    payloads: list[bytes],
    destination: tuple[str, int],
    deadline: float,
    results: dict[str, DiscoveredDevice],
) -> None:
    """Send each probe in turn and keep receiving until ``deadline``.

    Probes are spread across the listening window rather than sent back to back: UDP
    multicast is lossy and slow devices answer late, so a single burst under-reports.
    """
    send_at = [
        deadline - (deadline - time.monotonic()) * (1 - i / len(payloads))
        for i in range(len(payloads))
    ]
    pending = list(zip(send_at, payloads, strict=True))
    while True:
        now = time.monotonic()
        if now >= deadline:
            return
        while pending and pending[0][0] <= now:
            _, payload = pending.pop(0)
            try:
                sock.sendto(payload, destination)
            except OSError as exc:
                logger.debug("onveef: WS-Discovery probe send failed: %s", exc)
        next_event = min(pending[0][0], deadline) if pending else deadline
        sock.settimeout(max(0.001, next_event - now))
        try:
            data, sender = sock.recvfrom(65535)
        except TimeoutError:
            continue
        except OSError as exc:
            logger.debug("onveef: WS-Discovery receive error (continuing): %s", exc)
            continue
        _collect(results, data, str(sender[0]))


def discover(
    *,
    timeout_s: float = 3.0,
    types: str = DEFAULT_TYPES,
    interface_ip: str | list[str] | None = None,
    ttl: int = 2,
    probes: int = _DEFAULT_PROBES,
    ipv6: bool = False,
) -> list[DiscoveredDevice]:
    """Discover ONVIF devices on the LAN via WS-Discovery multicast Probes.

    Args:
        timeout_s: How long to listen for ``ProbeMatch`` replies, per interface.
        types: Space-separated device types to match; defaults to :data:`DEFAULT_TYPES`.
            Pass ``""`` to match every ONVIF device.
        interface_ip: Local NIC address(es) to send from. ``None`` (the default) probes
            every address :func:`local_ipv4_addresses` finds, plus the default route, so
            multi-homed hosts and Docker bridges are covered. Pass a single IP to pin one
            interface, or a list to choose several.
        ttl: Multicast TTL (router hops).
        probes: How many Probes to send per interface, spread across the listening window.
            UDP multicast is lossy; one probe can silently find nothing.
        ipv6: Also probe the IPv6 link-local multicast group ``ff02::c``. Best effort — a
            host without IPv6 multicast routing simply contributes no results.

    Returns:
        A de-duplicated list of :class:`DiscoveredDevice` across every interface probed.
    """
    if interface_ip is None:
        targets = local_ipv4_addresses() or ["0.0.0.0"]
    elif isinstance(interface_ip, str):
        targets = [interface_ip]
    else:
        targets = list(interface_ip) or ["0.0.0.0"]

    results: dict[str, DiscoveredDevice] = {}
    for bind_ip in targets:
        payloads = _probe_payloads(types, probes)
        try:
            sock = _open_socket(socket.AF_INET, bind_ip, ttl)
        except OSError as exc:
            logger.debug("onveef: cannot probe from %s: %s", bind_ip, exc)
            continue
        try:
            _listen(
                sock,
                payloads,
                (WS_DISCOVERY_ADDRESS, WS_DISCOVERY_PORT),
                time.monotonic() + timeout_s,
                results,
            )
        finally:
            sock.close()

    if ipv6:
        try:
            sock6 = _open_socket(socket.AF_INET6, "::", ttl)
        except OSError as exc:
            logger.debug("onveef: IPv6 WS-Discovery unavailable: %s", exc)
        else:
            try:
                _listen(
                    sock6,
                    _probe_payloads(types, probes),
                    (WS_DISCOVERY_ADDRESS_IPV6, WS_DISCOVERY_PORT),
                    time.monotonic() + timeout_s,
                    results,
                )
            finally:
                sock6.close()

    return list(results.values())


def probe_device(
    address: str,
    *,
    timeout_s: float = 2.0,
    types: str = DEFAULT_TYPES,
    port: int = WS_DISCOVERY_PORT,
) -> list[DiscoveredDevice]:
    """Probe one known address directly instead of multicasting.

    Useful when the device is on another subnet, multicast is filtered by the network, or
    you already know the IP and just want its XAddrs and scopes.
    """
    payload = build_probe(message_id=f"urn:uuid:{uuid.uuid4()}", types=types).encode("utf-8")
    results: dict[str, DiscoveredDevice] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout_s)
        sock.sendto(payload, (address, port))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                data, sender = sock.recvfrom(65535)
            except TimeoutError:
                break
            except OSError as exc:
                logger.debug("onveef: unicast probe of %s failed: %s", address, exc)
                break
            _collect(results, data, str(sender[0]))
    finally:
        sock.close()
    return list(results.values())


async def discover_async(
    *,
    timeout_s: float = 3.0,
    types: str = DEFAULT_TYPES,
    interface_ip: str | list[str] | None = None,
    ttl: int = 2,
    probes: int = _DEFAULT_PROBES,
) -> list[DiscoveredDevice]:
    """Async variant of :func:`discover` for use on an asyncio event loop.

    Probes every interface concurrently and retransmits like the sync version. IPv6 is not
    covered here; use :func:`discover` in a thread if you need it.
    """
    loop = asyncio.get_running_loop()
    if interface_ip is None:
        targets = local_ipv4_addresses() or ["0.0.0.0"]
    elif isinstance(interface_ip, str):
        targets = [interface_ip]
    else:
        targets = list(interface_ip) or ["0.0.0.0"]

    results: dict[str, DiscoveredDevice] = {}

    class _ProbeProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
            _collect(results, data, str(addr[0]))

        def error_received(self, exc: Exception) -> None:
            logger.debug("onveef: WS-Discovery datagram error (continuing): %s", exc)

    async def probe_from(bind_ip: str) -> None:
        try:
            transport, _ = await loop.create_datagram_endpoint(
                _ProbeProtocol,
                local_addr=(bind_ip, 0),
                family=socket.AF_INET,
                allow_broadcast=True,
            )
        except OSError as exc:
            logger.debug("onveef: cannot probe from %s: %s", bind_ip, exc)
            return
        try:
            raw = transport.get_extra_info("socket")
            if raw is not None:
                raw.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
                if bind_ip and bind_ip != "0.0.0.0":
                    raw.setsockopt(
                        socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(bind_ip)
                    )
            payloads = _probe_payloads(types, probes)
            interval = timeout_s / len(payloads)
            for payload in payloads:
                transport.sendto(payload, (WS_DISCOVERY_ADDRESS, WS_DISCOVERY_PORT))
                await asyncio.sleep(interval)
        finally:
            transport.close()

    await asyncio.gather(*(probe_from(ip) for ip in targets))
    return list(results.values())
