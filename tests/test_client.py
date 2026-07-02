from __future__ import annotations

import pytest

from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint
from onveef.exceptions import OnvifCapabilityMissingError

_ALL_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "media": "http://cam/onvif/media",
    "ptz": "http://cam/onvif/ptz",
    "analytics": "http://cam/onvif/analytics",
    "recording": "http://cam/onvif/recording",
    "search": "http://cam/onvif/search",
    "replay": "http://cam/onvif/replay",
}


def _client(services: dict[str, str] | None = None) -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr="http://cam/onvif/device_service",
            services=_ALL_SERVICES if services is None else services,
        ),
        credentials=OnvifCredentials(),
    )


def _stub(client: OnvifClient, xml: str) -> list[str]:
    captured: list[str] = []

    def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_get_recordings_dispatches_and_parses() -> None:
    client = _client()
    sent = _stub(
        client,
        "<GetRecordingsResponse><RecordingItem><RecordingToken>R0</RecordingToken>"
        "</RecordingItem></GetRecordingsResponse>",
    )
    recordings = client.get_recordings()
    assert recordings[0]["token"] == "R0"
    assert "GetRecordings" in sent[0]


def test_create_recording_returns_token() -> None:
    client = _client()
    _stub(
        client,
        "<CreateRecordingResponse><RecordingToken>R7</RecordingToken></CreateRecordingResponse>",
    )
    assert client.create_recording(source_id="s", source_name="n") == "R7"


def test_find_recordings_returns_search_token() -> None:
    client = _client()
    _stub(
        client,
        "<FindRecordingsResponse><SearchToken>S1</SearchToken></FindRecordingsResponse>",
    )
    assert client.find_recordings() == "S1"


def test_get_replay_uri() -> None:
    client = _client()
    _stub(client, "<GetReplayUriResponse><Uri>rtsp://cam/replay</Uri></GetReplayUriResponse>")
    assert client.get_replay_uri(recording_token="R0") == "rtsp://cam/replay"


def test_osd_requires_media1() -> None:
    client = _client({"device": "http://cam/onvif/device_service"})
    with pytest.raises(OnvifCapabilityMissingError):
        client.get_osds()


def test_create_osd_returns_token() -> None:
    client = _client()
    _stub(client, "<CreateOSDResponse><OSDToken>OSD9</OSDToken></CreateOSDResponse>")
    token = client.create_osd(video_source_configuration_token="VSC0", plain_text="hi")
    assert token == "OSD9"


def test_get_scopes_dispatches_to_device() -> None:
    client = _client()
    sent = _stub(
        client,
        "<GetScopesResponse><Scopes><ScopeDef>Fixed</ScopeDef>"
        "<ScopeItem>onvif://x</ScopeItem></Scopes></GetScopesResponse>",
    )
    scopes = client.get_scopes()
    assert scopes[0]["scope_item"] == "onvif://x"
    assert "GetScopes" in sent[0]


def test_create_rules_dispatches_to_analytics() -> None:
    client = _client()
    sent = _stub(client, "<CreateRulesResponse/>")
    client.create_rules(
        configuration_token="CFG0",
        rules=[{"name": "R", "type": "tt:LineDetector", "parameters": {}}],
    )
    assert "CreateRules" in sent[0]
    assert 'Name="R"' in sent[0]


def test_soap_fault_raises() -> None:
    from onveef.exceptions import OnvifFaultError

    client = _client()
    _stub(
        client,
        "<Envelope><Body><Fault><Reason><Text>Sender InvalidArgVal: bad token</Text></Reason>"
        "</Fault></Body></Envelope>",
    )
    with pytest.raises(OnvifFaultError):
        client.get_recordings()


def test_unsupported_optional_method_raises_not_supported() -> None:
    from onveef.exceptions import OnvifOperationNotSupportedError

    client = _client()
    _stub(
        client,
        "<Envelope><Body><Fault><Reason><Text>This optional method is not implemented"
        "</Text></Reason></Fault></Body></Envelope>",
    )
    with pytest.raises(OnvifOperationNotSupportedError):
        client.get_system_support_information()


def test_missing_service_raises_capability_missing() -> None:
    client = _client({"device": "http://cam/onvif/device_service"})
    with pytest.raises(OnvifCapabilityMissingError):
        client.get_recordings()


def test_relay_falls_back_to_device_service() -> None:
    client = _client()
    sent = _stub(client, "<GetRelayOutputsResponse/>")
    client.get_relay_outputs()
    assert "<tds:GetRelayOutputs/>" in sent[0]


def test_relay_routes_to_deviceio_when_advertised() -> None:
    services = {**_ALL_SERVICES, "deviceio": "http://cam/onvif/deviceio"}
    client = _client(services)
    sent = _stub(client, "<GetRelayOutputsResponse/>")
    client.get_relay_outputs()
    assert "<tmd:GetRelayOutputs/>" in sent[0]
