from __future__ import annotations

from collections.abc import Callable

from onveef import envelopes, parsers
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint

_ALL_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "media": "http://cam/onvif/media",
    "ptz": "http://cam/onvif/ptz",
    "events": "http://cam/onvif/events",
}


def _client(
    services: dict[str, str] | None = None, *, creds: OnvifCredentials | None = None
) -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr="http://cam/onvif/device_service",
            services=_ALL_SERVICES if services is None else services,
        ),
        credentials=creds or OnvifCredentials(),
    )


def _stub(client: OnvifClient, responder: Callable[[str], tuple[int, str]]) -> list[str]:
    captured: list[str] = []

    def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        return responder(envelope)

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_ws_security_digest_is_default() -> None:
    env = envelopes.build_envelope("<tds:GetHostname/>", username="admin", password="pw")
    assert "PasswordDigest" in env
    assert "<wsse:Nonce" in env
    assert "PasswordText" not in env


def test_ws_security_password_text_mode() -> None:
    env = envelopes.build_envelope(
        "<tds:GetHostname/>", username="admin", password="pw", use_password_text=True
    )
    assert "PasswordText" in env
    assert ">pw</wsse:Password>" in env
    assert "PasswordDigest" not in env


def test_ws_security_timestamp() -> None:
    env = envelopes.build_envelope(
        "<tds:GetHostname/>", username="admin", password="pw", add_timestamp=True
    )
    assert "<wsu:Timestamp" in env
    assert "<wsu:Expires>" in env


def test_get_service_capabilities_builder_prefixes() -> None:
    assert envelopes.get_service_capabilities("ptz") == "<tptz:GetServiceCapabilities/>"
    assert envelopes.get_service_capabilities("media2") == "<trt2:GetServiceCapabilities/>"
    assert envelopes.get_service_capabilities("deviceio") == "<tmd:GetServiceCapabilities/>"
    assert envelopes.get_service_capabilities("unknown") == "<tds:GetServiceCapabilities/>"


def test_parse_service_capabilities() -> None:
    xml = (
        "<GetServiceCapabilitiesResponse>"
        '<Capabilities MaximumNumberOfProfiles="24" SnapshotUri="true"/>'
        "</GetServiceCapabilitiesResponse>"
    )
    caps = parsers.parse_service_capabilities(xml)
    assert caps["@MaximumNumberOfProfiles"] == "24"
    assert caps["@SnapshotUri"] == "true"


def test_stream_uri_transport_options() -> None:
    m1 = envelopes.media_get_stream_uri(
        profile_token="P0", use_media2=False, stream="RTP-Multicast", protocol="UDP"
    )
    assert "<tt:Stream>RTP-Multicast</tt:Stream>" in m1
    assert "<tt:Protocol>UDP</tt:Protocol>" in m1
    m2 = envelopes.media_get_stream_uri(
        profile_token="P0", use_media2=True, protocol2="RtspOverHttp"
    )
    assert "<trt2:Protocol>RtspOverHttp</trt2:Protocol>" in m2
    default = envelopes.media_get_stream_uri(profile_token="P0", use_media2=False)
    assert "<tt:Stream>RTP-Unicast</tt:Stream>" in default


def test_set_synchronization_point_and_deviceio_builders() -> None:
    assert envelopes.events_set_synchronization_point() == "<tev:SetSynchronizationPoint/>"
    assert envelopes.device_get_relay_output_options() == "<tmd:GetRelayOutputOptions/>"
    assert (
        "<tmd:RelayOutputToken>R0</tmd:RelayOutputToken>"
        in envelopes.device_get_relay_output_options(token="R0")
    )
    assert envelopes.device_get_serial_ports() == "<tmd:GetSerialPorts/>"


def test_parse_relay_output_options() -> None:
    xml = (
        "<GetRelayOutputOptionsResponse>"
        '<RelayOutputOptions token="R0"><Mode>Bistable</Mode><Mode>Monostable</Mode>'
        "<Discrete>true</Discrete></RelayOutputOptions>"
        "</GetRelayOutputOptionsResponse>"
    )
    out = parsers.parse_relay_output_options(xml)
    assert out[0]["token"] == "R0"
    assert out[0]["modes"] == ["Bistable", "Monostable"]
    assert out[0]["discrete"] is True


def test_parse_network_interfaces_ipv4_and_ipv6() -> None:
    xml = """
    <GetNetworkInterfacesResponse>
      <NetworkInterfaces token="eth0">
        <Enabled>true</Enabled>
        <Info><Name>eth0</Name><HwAddress>00:11:22:33:44:55</HwAddress><MTU>1500</MTU></Info>
        <IPv4><Enabled>true</Enabled><Config>
          <Manual><Address>192.168.1.64</Address><PrefixLength>24</PrefixLength></Manual>
          <DHCP>false</DHCP>
        </Config></IPv4>
        <IPv6><Enabled>true</Enabled><Config>
          <LinkLocal><Address>fe80::1</Address><PrefixLength>64</PrefixLength></LinkLocal>
          <DHCP>Off</DHCP>
        </Config></IPv6>
      </NetworkInterfaces>
    </GetNetworkInterfacesResponse>
    """
    iface = parsers.parse_network_interfaces(xml)[0]
    assert iface["addresses"] == ["192.168.1.64"]
    assert iface["ipv4"]["addresses"][0]["prefix_length"] == 24
    assert iface["ipv4"]["dhcp"] == "false"
    assert iface["ipv6"]["addresses"][0]["address"] == "fe80::1"
    assert iface["ipv6"]["addresses"][0]["prefix_length"] == 64


def test_client_get_service_capabilities_dispatch() -> None:
    client = _client()
    sent = _stub(
        client,
        lambda _e: (
            200,
            "<GetServiceCapabilitiesResponse><Capabilities "
            'MaximumNumberOfProfiles="8"/></GetServiceCapabilitiesResponse>',
        ),
    )
    caps = client.get_service_capabilities("ptz")
    assert "GetServiceCapabilities" in sent[0]
    assert caps["@MaximumNumberOfProfiles"] == "8"


def test_client_relay_output_options_routes_to_deviceio() -> None:
    client = _client({**_ALL_SERVICES, "deviceio": "http://cam/dio"})
    sent = _stub(client, lambda _e: (200, "<GetRelayOutputOptionsResponse/>"))
    client.get_relay_output_options()
    assert "<tmd:GetRelayOutputOptions/>" in sent[0]


def test_password_text_fallback_after_digest_401() -> None:
    """The digest-401 path retries once with PasswordText; clock sync is pinned off here."""
    client = _client(creds=OnvifCredentials("admin", "pw"))
    client._clock_synced = True

    def responder(envelope: str) -> tuple[int, str]:
        if "PasswordText" in envelope:
            return 200, "<GetHostnameResponse><Name>cam</Name></GetHostnameResponse>"
        return 401, ""

    sent = _stub(client, responder)
    assert client.get_hostname() == "cam"
    assert any("PasswordDigest" in e for e in sent)
    assert any("PasswordText" in e for e in sent)
