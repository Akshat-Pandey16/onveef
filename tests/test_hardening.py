from __future__ import annotations

import time

import pytest

from onveef import envelopes, parsers
from onveef.breaker import CircuitBreaker
from onveef.client import OnvifClient, OnvifCredentials, OnvifEndpoint
from onveef.exceptions import (
    OnvifCapabilityMissingError,
    OnvifNotConfiguredError,
    OnvifServiceUnavailableError,
    OnvifTimeoutError,
    OnvifTransportError,
)


def _stub_by_operation(client: OnvifClient, responses: dict[str, str]) -> list[str]:
    """Stub ``_post_soap`` to answer with a response chosen by an operation marker in the envelope."""
    captured: list[str] = []

    def fake_post_soap(*, url: str, envelope: str, content_type: str) -> tuple[int, str]:
        captured.append(envelope)
        for marker, xml in responses.items():
            if marker in envelope:
                return 200, xml
        raise AssertionError(f"unexpected envelope: {envelope[:200]}")

    client._post_soap = fake_post_soap  # type: ignore[method-assign]
    return captured


def test_simple_constructor_derives_device_url() -> None:
    with OnvifClient("192.168.1.64", 80, "admin", "secret") as client:
        assert client.endpoint.device_xaddr == "http://192.168.1.64:80/onvif/device_service"


def test_simple_constructor_use_https() -> None:
    with OnvifClient("192.168.1.64", 443, "admin", "secret", use_https=True) as client:
        assert client.endpoint.device_xaddr == "https://192.168.1.64:443/onvif/device_service"


def test_simple_constructor_full_url_passes_through() -> None:
    with OnvifClient("http://cam.local/onvif/device_service") as client:
        assert client.endpoint.device_xaddr == "http://cam.local/onvif/device_service"


def test_constructor_missing_host_raises() -> None:
    with pytest.raises(OnvifNotConfiguredError):
        OnvifClient()


def test_credentials_repr_hides_password() -> None:
    creds = OnvifCredentials("admin", "hunter2")
    text = repr(creds)
    assert "admin" in text
    assert "hunter2" not in text
    assert "password" not in text


def test_lazy_auto_discovery_from_host_form() -> None:
    client = OnvifClient("192.168.1.64", 80, "admin", "secret")
    services_xml = (
        "<GetServicesResponse>"
        "<Service><Namespace>http://www.onvif.org/ver10/device/wsdl</Namespace>"
        "<XAddr>http://192.168.1.64/onvif/device_service</XAddr></Service>"
        "<Service><Namespace>http://www.onvif.org/ver10/media/wsdl</Namespace>"
        "<XAddr>http://192.168.1.64/onvif/media</XAddr></Service>"
        "</GetServicesResponse>"
    )
    profiles_xml = (
        "<GetProfilesResponse><Profiles token=\"P0\"><Name>Main</Name></Profiles>"
        "</GetProfilesResponse>"
    )
    sent = _stub_by_operation(
        client, {"GetServices": services_xml, "GetProfiles": profiles_xml}
    )
    profiles = client.get_profiles()
    client.close()
    assert profiles[0]["token"] == "P0"
    assert any("GetServices" in e for e in sent)
    assert any("GetProfiles" in e for e in sent)


def test_endpoint_form_missing_service_raises_without_discovery() -> None:
    client = OnvifClient(
        endpoint=OnvifEndpoint(
            device_xaddr="http://cam/onvif/device_service",
            services={"device": "http://cam/onvif/device_service"},
        ),
        credentials=OnvifCredentials(),
    )
    with pytest.raises(OnvifCapabilityMissingError):
        client.get_profiles()
    client.close()


def test_parse_services_discovers_analytics_ver20() -> None:
    xml = (
        "<GetServicesResponse>"
        "<Service><Namespace>http://www.onvif.org/ver20/analytics/wsdl</Namespace>"
        "<XAddr>http://cam/onvif/analytics</XAddr></Service>"
        "</GetServicesResponse>"
    )
    services = parsers.parse_services(xml)
    assert services["analytics"] == "http://cam/onvif/analytics"


def test_parse_profiles_media2_attribute_video_encoder() -> None:
    xml = (
        "<GetProfilesResponse>"
        "<Profiles token=\"P0\" fixed=\"true\"><Name>MainStream</Name>"
        "<Configurations>"
        "<VideoEncoder token=\"VE0\" GovLength=\"30\" Profile=\"High\" Encoding=\"H264\">"
        "<Name>VE</Name>"
        "<Resolution><Width>1920</Width><Height>1080</Height></Resolution>"
        "<Quality>4</Quality>"
        "<RateControl FrameRateLimit=\"25\" BitrateLimit=\"4096\" EncodingInterval=\"1\"/>"
        "</VideoEncoder>"
        "</Configurations>"
        "</Profiles>"
        "</GetProfilesResponse>"
    )
    profiles = parsers.parse_profiles(xml)
    enc = profiles[0]["video_encoder"]
    assert enc["token"] == "VE0"
    assert enc["encoding"] == "H264"
    assert enc["gop"] == 30
    assert enc["profile"] == "High"
    assert enc["width"] == 1920
    assert enc["height"] == 1080
    assert enc["fps_limit"] == 25
    assert enc["bitrate_kbps"] == 4096
    assert enc["encoding_interval"] == 1


def test_parse_fault_soap11_faultstring() -> None:
    xml = (
        "<soap:Envelope xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\">"
        "<soap:Body><soap:Fault>"
        "<faultcode>soap:Server</faultcode>"
        "<faultstring>Optional action is not implemented</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    fault = parsers.parse_fault(xml)
    assert fault == "Optional action is not implemented"
    assert parsers.fault_is_unsupported(fault) is True


def test_parse_pull_messages_extracts_times_deep() -> None:
    xml = (
        "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\">"
        "<s:Body><PullMessagesResponse>"
        "<CurrentTime>2026-07-02T12:00:00Z</CurrentTime>"
        "<TerminationTime>2026-07-02T12:05:00Z</TerminationTime>"
        "<NotificationMessage><Topic>tns1:VideoSource/MotionAlarm</Topic>"
        "<Message><Message UtcTime=\"2026-07-02T12:00:01Z\" PropertyOperation=\"Changed\">"
        "<Source><SimpleItem Name=\"VideoSourceToken\" Value=\"VS0\"/></Source>"
        "<Data><SimpleItem Name=\"State\" Value=\"true\"/></Data>"
        "</Message></Message></NotificationMessage>"
        "</PullMessagesResponse></s:Body></s:Envelope>"
    )
    out = parsers.parse_pull_messages(xml)
    assert out["current_time"] == "2026-07-02T12:00:00Z"
    assert out["termination_time"] == "2026-07-02T12:05:00Z"
    assert out["messages"][0]["data"]["State"] == "true"


def test_parse_create_pull_point_extracts_times_deep() -> None:
    xml = (
        "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\">"
        "<s:Body><CreatePullPointSubscriptionResponse>"
        "<SubscriptionReference><Address>http://cam/onvif/sub/0</Address></SubscriptionReference>"
        "<CurrentTime>2026-07-02T12:00:00Z</CurrentTime>"
        "<TerminationTime>2026-07-02T12:10:00Z</TerminationTime>"
        "</CreatePullPointSubscriptionResponse></s:Body></s:Envelope>"
    )
    out = parsers.parse_create_pull_point(xml)
    assert out["subscription_url"] == "http://cam/onvif/sub/0"
    assert out["current_time"] == "2026-07-02T12:00:00Z"
    assert out["termination_time"] == "2026-07-02T12:10:00Z"


def test_parse_event_properties_keeps_tns1_prefix() -> None:
    xml = (
        "<GetEventPropertiesResponse xmlns:tns1=\"http://www.onvif.org/ver10/topics\">"
        "<TopicSet>"
        "<tns1:VideoSource><MotionAlarm><MessageDescription/></MotionAlarm></tns1:VideoSource>"
        "</TopicSet></GetEventPropertiesResponse>"
    )
    out = parsers.parse_event_properties(xml)
    assert out["topics"] == ["tns1:VideoSource/MotionAlarm"]


def test_media2_set_video_encoder_uses_attributes() -> None:
    body = envelopes.media2_set_video_encoder_configuration(
        token="VE0",
        name="Main",
        encoding="H264",
        width=1920,
        height=1080,
        quality=4.0,
        fps=25,
        bitrate_kbps=4096,
        gop=30,
        h264_profile="High",
    )
    assert 'Encoding="H264"' in body
    assert 'GovLength="30"' in body
    assert 'Profile="High"' in body
    assert 'FrameRateLimit="25"' in body
    assert 'BitrateLimit="4096"' in body
    assert "<tt:Encoding>" not in body
    assert "<tt:GovLength>" not in body
    assert "<tt:Profile>" not in body


def test_build_envelope_wsa_action_adds_message_id_and_reply_to() -> None:
    xml = envelopes.build_envelope(
        "<trt:GetProfiles/>",
        wsa_action="http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest",
    )
    assert "<wsa:Action" in xml
    assert "<wsa:MessageID>" in xml
    assert "<wsa:ReplyTo>" in xml


def test_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker(window_s=60.0, threshold=2, open_s=30.0)
    key = "dev"
    cb.record_failure(key)
    assert cb.is_open(key) is False
    cb.record_failure(key)
    assert cb.is_open(key) is True


def test_breaker_half_open_single_probe_and_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr("onveef.breaker.time.monotonic", lambda: clock["t"])
    cb = CircuitBreaker(window_s=60.0, threshold=2, open_s=30.0)
    key = "dev"

    cb.record_failure(key)
    cb.record_failure(key)
    assert cb.is_open(key) is True

    clock["t"] += 31.0
    assert cb.is_open(key) is False
    assert cb.is_open(key) is True

    cb.record_success(key)
    assert cb.is_open(key) is False

    cb.record_failure(key)
    cb.record_failure(key)
    assert cb.is_open(key) is True
    clock["t"] += 31.0
    assert cb.is_open(key) is False
    cb.record_failure(key)
    assert cb.is_open(key) is True


def test_breaker_half_open_real_time_probe() -> None:
    cb = CircuitBreaker(window_s=60.0, threshold=1, open_s=0.02)
    key = "dev"
    cb.record_failure(key)
    assert cb.is_open(key) is True
    deadline = time.monotonic() + 0.035
    while time.monotonic() < deadline:
        pass
    assert cb.is_open(key) is False
    assert cb.is_open(key) is True
    cb.record_success(key)
    assert cb.is_open(key) is False


def test_exception_retryable_flags() -> None:
    assert OnvifTimeoutError("t").retryable is True
    assert OnvifServiceUnavailableError("s").retryable is True
    assert OnvifTransportError("x").retryable is False
    assert OnvifTransportError("x", retryable=True).retryable is True


def test_py_typed_marker_exists() -> None:
    import pathlib

    import onveef

    marker = pathlib.Path(onveef.__file__).parent / "py.typed"
    assert marker.is_file()
