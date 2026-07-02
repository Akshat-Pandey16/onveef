from __future__ import annotations

import asyncio
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from onveef.parsers import child_text, find_all_local, find_local, parse_xml

WS_DISCOVERY_ADDRESS = "239.255.255.250"
WS_DISCOVERY_PORT = 3702
_MULTICAST_TO = "urn:schemas-xmlsoap-org:ws:2005:04:discovery"
_PROBE_ACTION = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe"
_NVT_TYPE = "dn:NetworkVideoTransmitter"

_DEFAULT_TYPES = "dn:NetworkVideoTransmitter tds:Device"

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


def build_probe(*, message_id: str, types: str = _NVT_TYPE) -> str:
    return _ENVELOPE.format(message_id=message_id, types=types)


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


def discover(
    *,
    timeout_s: float = 3.0,
    types: str = _DEFAULT_TYPES,
    interface_ip: str = "0.0.0.0",
    ttl: int = 2,
) -> list[DiscoveredDevice]:
    """Discover ONVIF devices on the LAN via a WS-Discovery multicast Probe.

    Args:
        timeout_s: How long to listen for ProbeMatch replies.
        types: Space-separated device types to match. Defaults to both
            ``NetworkVideoTransmitter`` and ``Device`` so cameras, NVRs and access-control
            devices all respond; pass ``""`` to match every ONVIF device.
        interface_ip: Local NIC address to send from (use a specific IP on multi-homed
            hosts so the probe egresses the intended network).
        ttl: Multicast TTL (number of router hops).

    Returns:
        A de-duplicated list of :class:`DiscoveredDevice`.
    """
    message_id = f"urn:uuid:{uuid.uuid4()}"
    probe = build_probe(message_id=message_id, types=types).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        if interface_ip not in ("", "0.0.0.0"):
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip)
            )
        sock.bind((interface_ip, 0))
        sock.sendto(probe, (WS_DISCOVERY_ADDRESS, WS_DISCOVERY_PORT))
        results: dict[str, DiscoveredDevice] = {}
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, sender = sock.recvfrom(65535)
            except (TimeoutError, OSError):
                break
            for device in parse_probe_matches(data.decode("utf-8", errors="replace")):
                if not device.address:
                    device.address = sender[0]
                key = device.endpoint_reference or device.address or sender[0]
                results[key] = device
        return list(results.values())
    finally:
        sock.close()


async def discover_async(
    *,
    timeout_s: float = 3.0,
    types: str = _DEFAULT_TYPES,
    interface_ip: str = "0.0.0.0",
    ttl: int = 2,
) -> list[DiscoveredDevice]:
    """Async variant of :func:`discover` for use on an asyncio event loop."""
    loop = asyncio.get_running_loop()
    message_id = f"urn:uuid:{uuid.uuid4()}"
    probe = build_probe(message_id=message_id, types=types).encode("utf-8")
    results: dict[str, DiscoveredDevice] = {}

    class _ProbeProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
            for device in parse_probe_matches(data.decode("utf-8", errors="replace")):
                if not device.address:
                    device.address = addr[0]
                key = device.endpoint_reference or device.address or addr[0]
                results[key] = device

    transport, _ = await loop.create_datagram_endpoint(
        _ProbeProtocol,
        local_addr=(interface_ip, 0),
        family=socket.AF_INET,
        allow_broadcast=True,
    )
    try:
        raw = transport.get_extra_info("socket")
        if raw is not None:
            raw.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            if interface_ip not in ("", "0.0.0.0"):
                raw.setsockopt(
                    socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip)
                )
        transport.sendto(probe, (WS_DISCOVERY_ADDRESS, WS_DISCOVERY_PORT))
        await asyncio.sleep(timeout_s)
    finally:
        transport.close()
    return list(results.values())
