from __future__ import annotations

from onveef import envelopes
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint

_SERVICES = {
    "device": "http://cam/onvif/device_service",
    "media2": "http://cam/onvif/media2",
    "events": "http://cam/onvif/events",
}


def _client() -> OnvifClient:
    return OnvifClient(
        endpoint=OnvifEndpoint(device_xaddr="http://cam/onvif/device_service", services=_SERVICES),
        credentials=OnvifCredentials(),
    )


def _stub(client: OnvifClient, xml: str) -> list[str]:
    captured: list[str] = []

    def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        return 200, xml

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_media2_create_profile_with_configurations() -> None:
    body = envelopes.media2_create_profile(
        name="Main", configurations=[{"type": "VideoEncoder", "token": "VE0"}]
    )
    assert "<trt2:Name>Main</trt2:Name>" in body
    assert "<trt2:Type>VideoEncoder</trt2:Type>" in body
    assert "<trt2:Token>VE0</trt2:Token>" in body


def test_media2_get_profiles_type_filter() -> None:
    assert envelopes.media2_get_profiles() == "<trt2:GetProfiles/>"
    body = envelopes.media2_get_profiles(types=["VideoEncoder", "AudioEncoder"])
    assert "<trt2:Type>VideoEncoder</trt2:Type>" in body
    assert "<trt2:Type>AudioEncoder</trt2:Type>" in body


def test_media2_add_and_remove_configuration() -> None:
    add = envelopes.media2_add_configuration(
        profile_token="P0", configurations=[{"type": "Metadata", "token": "MD0"}]
    )
    assert "<trt2:ProfileToken>P0</trt2:ProfileToken>" in add
    assert "<trt2:Type>Metadata</trt2:Type>" in add
    assert "<trt2:Token>MD0</trt2:Token>" in add
    remove = envelopes.media2_remove_configuration(
        profile_token="P0", configurations=[{"type": "Metadata"}]
    )
    assert "<trt2:RemoveConfiguration>" in remove
    assert "<trt2:Type>Metadata</trt2:Type>" in remove
    assert "<trt2:Token>" not in remove


def test_events_subscribe_builder() -> None:
    body = envelopes.events_subscribe(
        consumer_address="http://host/consumer",
        topic_filter="tns1:RuleEngine/CellMotionDetector/Motion",
    )
    assert "<wsnt:Subscribe>" in body
    assert "<wsa:Address>http://host/consumer</wsa:Address>" in body
    assert "ConcreteSet" in body
    assert "tns1:RuleEngine/CellMotionDetector/Motion" in body
    assert "<wsnt:Filter>" not in envelopes.events_subscribe(consumer_address="http://h/c")


def test_client_media2_create_profile_returns_token() -> None:
    client = _client()
    sent = _stub(client, "<CreateProfileResponse><Token>P9</Token></CreateProfileResponse>")
    assert client.media2_create_profile(name="Main") == "P9"
    assert "<trt2:CreateProfile>" in sent[0]


def test_client_events_subscribe_parses_manager() -> None:
    client = _client()
    sent = _stub(
        client,
        "<SubscribeResponse><SubscriptionReference><Address>http://cam/sub-1</Address>"
        "</SubscriptionReference><CurrentTime>2026-07-02T00:00:00Z</CurrentTime>"
        "<TerminationTime>2026-07-02T00:01:00Z</TerminationTime></SubscribeResponse>",
    )
    result = client.events_subscribe(consumer_address="http://host/consumer")
    assert result["subscription_url"] == "http://cam/sub-1"
    assert "<wsnt:Subscribe>" in sent[0]
