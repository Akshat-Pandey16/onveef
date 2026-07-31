"""Tests for the WS-Discovery robustness work: retransmits, multi-NIC, error tolerance."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from onveef import wsdiscovery

_MATCH = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <s:Body><d:ProbeMatches><d:ProbeMatch>
    <a:EndpointReference><a:Address>urn:uuid:{uid}</a:Address></a:EndpointReference>
    <d:Types>dn:NetworkVideoTransmitter</d:Types>
    <d:Scopes>onvif://www.onvif.org/name/Cam{uid} onvif://www.onvif.org/hardware/DS</d:Scopes>
    <d:XAddrs>http://10.0.0.{uid}/onvif/device_service</d:XAddrs>
    <d:MetadataVersion>1</d:MetadataVersion>
  </d:ProbeMatch></d:ProbeMatches></s:Body>
</s:Envelope>"""


class FakeSocket:
    """A socket stand-in that replays a scripted sequence of recvfrom outcomes."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False
        self.options: list[tuple[int, int, Any]] = []

    def setsockopt(self, level: int, option: int, value: Any) -> None:
        self.options.append((level, option, value))

    def bind(self, addr: tuple[str, int]) -> None:
        self.bound = addr

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendto(self, payload: bytes, destination: tuple[str, int]) -> None:
        self.sent.append((payload, destination))

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        if not self.script:
            raise TimeoutError
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        payload, sender = item
        return payload, sender

    def close(self) -> None:
        self.closed = True


def test_build_probe_defaults_match_discover_defaults() -> None:
    """The documented escape hatch must not probe more narrowly than discover()."""
    probe = wsdiscovery.build_probe(message_id="urn:uuid:1")
    assert wsdiscovery.DEFAULT_TYPES in probe
    assert "tds:Device" in probe


def test_probes_are_retransmitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """UDP multicast is lossy; a single probe is not enough."""
    fake = FakeSocket([])
    monkeypatch.setattr(wsdiscovery, "_open_socket", lambda *_a, **_k: fake)
    wsdiscovery.discover(timeout_s=0.15, interface_ip="0.0.0.0", probes=3)
    assert len(fake.sent) == 3
    assert {destination for _, destination in fake.sent} == {
        (wsdiscovery.WS_DISCOVERY_ADDRESS, wsdiscovery.WS_DISCOVERY_PORT)
    }


def test_each_probe_has_a_distinct_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket([])
    monkeypatch.setattr(wsdiscovery, "_open_socket", lambda *_a, **_k: fake)
    wsdiscovery.discover(timeout_s=0.15, interface_ip="0.0.0.0", probes=3)
    ids = {payload.split(b"<a:MessageID>")[1].split(b"</")[0] for payload, _ in fake.sent}
    assert len(ids) == 3


def test_receive_loop_survives_an_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows ICMP port-unreachable used to truncate discovery silently."""
    fake = FakeSocket(
        [
            ConnectionResetError("port unreachable"),
            (_MATCH.format(uid="7").encode(), ("10.0.0.7", 3702)),
        ]
    )
    monkeypatch.setattr(wsdiscovery, "_open_socket", lambda *_a, **_k: fake)
    devices = wsdiscovery.discover(timeout_s=0.3, interface_ip="0.0.0.0", probes=1)
    assert len(devices) == 1
    assert devices[0].device_service == "http://10.0.0.7/onvif/device_service"
    assert devices[0].name == "Cam7"


def test_every_interface_is_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 0.0.0.0 bind egresses one NIC; multi-homed hosts need one socket each."""
    binds: list[str] = []
    sockets: list[FakeSocket] = []

    def fake_open(family: int, bind_ip: str, ttl: int) -> FakeSocket:
        binds.append(bind_ip)
        fake = FakeSocket([(_MATCH.format(uid=str(len(binds))).encode(), (bind_ip, 3702))])
        sockets.append(fake)
        return fake

    monkeypatch.setattr(wsdiscovery, "_open_socket", fake_open)
    monkeypatch.setattr(wsdiscovery, "local_ipv4_addresses", lambda: ["10.0.0.2", "172.17.0.1"])
    devices = wsdiscovery.discover(timeout_s=0.2, probes=1)
    assert binds == ["10.0.0.2", "172.17.0.1"]
    assert len(devices) == 2
    assert all(sock.closed for sock in sockets)


def test_a_dead_interface_does_not_abort_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(family: int, bind_ip: str, ttl: int) -> FakeSocket:
        if bind_ip == "10.0.0.2":
            raise OSError("cannot assign requested address")
        return FakeSocket([(_MATCH.format(uid="9").encode(), (bind_ip, 3702))])

    monkeypatch.setattr(wsdiscovery, "_open_socket", fake_open)
    monkeypatch.setattr(wsdiscovery, "local_ipv4_addresses", lambda: ["10.0.0.2", "172.17.0.1"])
    devices = wsdiscovery.discover(timeout_s=0.2, probes=1)
    assert len(devices) == 1


def test_results_are_deduplicated_across_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(family: int, bind_ip: str, ttl: int) -> FakeSocket:
        return FakeSocket([(_MATCH.format(uid="5").encode(), (bind_ip, 3702))])

    monkeypatch.setattr(wsdiscovery, "_open_socket", fake_open)
    monkeypatch.setattr(wsdiscovery, "local_ipv4_addresses", lambda: ["10.0.0.2", "172.17.0.1"])
    assert len(wsdiscovery.discover(timeout_s=0.2, probes=1)) == 1


def test_explicit_interface_list_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    binds: list[str] = []

    def fake_open(family: int, bind_ip: str, ttl: int) -> FakeSocket:
        binds.append(bind_ip)
        return FakeSocket([])

    monkeypatch.setattr(wsdiscovery, "_open_socket", fake_open)
    wsdiscovery.discover(timeout_s=0.1, interface_ip=["1.1.1.1", "2.2.2.2"], probes=1)
    assert binds == ["1.1.1.1", "2.2.2.2"]


def test_ipv6_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    families: list[int] = []

    def fake_open(family: int, bind_ip: str, ttl: int) -> FakeSocket:
        families.append(family)
        return FakeSocket([])

    monkeypatch.setattr(wsdiscovery, "_open_socket", fake_open)
    monkeypatch.setattr(wsdiscovery, "local_ipv4_addresses", lambda: ["10.0.0.2"])

    wsdiscovery.discover(timeout_s=0.1, probes=1)
    assert socket.AF_INET6 not in families

    families.clear()
    wsdiscovery.discover(timeout_s=0.1, probes=1, ipv6=True)
    assert socket.AF_INET6 in families


def test_unicast_probe_targets_one_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multicast is often filtered; a known IP should still be probeable."""
    fake = FakeSocket([(_MATCH.format(uid="3").encode(), ("10.0.0.3", 3702))])
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: fake)
    devices = wsdiscovery.probe_device("10.0.0.3", timeout_s=0.2)
    assert fake.sent[0][1] == ("10.0.0.3", 3702)
    assert devices[0].name == "Cam3"


def test_local_ipv4_addresses_excludes_loopback() -> None:
    assert all(not a.startswith("127.") for a in wsdiscovery.local_ipv4_addresses())


async def test_discover_async_retransmits(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[bytes] = []

    class FakeTransport:
        def get_extra_info(self, _name: str) -> None:
            return None

        def sendto(self, payload: bytes, _destination: tuple[str, int]) -> None:
            sent.append(payload)

        def close(self) -> None:
            return None

    async def fake_endpoint(*_a: Any, **_k: Any) -> tuple[FakeTransport, None]:
        return FakeTransport(), None

    import asyncio

    monkeypatch.setattr(
        asyncio.get_running_loop(), "create_datagram_endpoint", fake_endpoint, raising=False
    )
    monkeypatch.setattr(wsdiscovery, "local_ipv4_addresses", lambda: ["10.0.0.2"])
    await wsdiscovery.discover_async(timeout_s=0.06, probes=3)
    assert len(sent) == 3
