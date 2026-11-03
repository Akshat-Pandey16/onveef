"""Writes that change one setting must not reset the others.

ONVIF ``Set*Configuration`` operations replace a configuration as a whole. These tests pin
that the setters send back what they did not change — multicast, session timeout, rate
control mode, the metadata event filter, crop bounds — and that the read-modify-write
helpers merge, validate and route a change correctly, using a real CP Plus capture.
"""

from __future__ import annotations

import inspect
import pathlib
import re
from collections.abc import Callable

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef import envelopes, updates
from onveef.client import OnvifCredentials
from onveef.exceptions import (
    OnvifCapabilityMissingError,
    OnvifFaultError,
    OnvifValidationError,
)

_CPPLUS = pathlib.Path(__file__).parent / "fixtures" / "cpplus"
_FAULT = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault><s:Code>'
    "<s:Value>s:Receiver</s:Value><s:Subcode><s:Value>ter:InvalidArgVal</s:Value></s:Subcode>"
    "</s:Code><s:Reason><s:Text>{reason}</s:Text></s:Reason></s:Fault></s:Body></s:Envelope>"
)


def _body(envelope: str) -> str:
    return envelope.split("<s:Body>", 1)[1]


def _operation(envelope: str) -> tuple[str, str]:
    match = re.match(r"<(\w+):(\w+)", _body(envelope))
    assert match is not None
    return match.group(1), match.group(2)


def cpplus(*, refuse_media2_writes: bool = False) -> Callable[[str], tuple[int, str]]:
    """Answer reads from the recorded CP Plus camera; accept (or refuse) writes."""

    def respond(envelope: str) -> tuple[int, str]:
        prefix, operation = _operation(envelope)
        if operation.startswith(("Set", "Create", "Add", "Remove", "Delete")):
            if refuse_media2_writes and prefix == "trt2":
                return 400, _FAULT.format(reason="Refused")
            return 200, f"<{operation}Response/>"
        token = re.search(r"<\w+:(?:ConfigurationToken|VideoSourceToken)>([^<]*)<", _body(envelope))
        name = ("Media2-" if prefix == "trt2" else "") + operation
        if token is not None:
            name += f"-{token.group(1)}"
        path = _CPPLUS / f"{name}.xml"
        if not path.exists():
            return 400, _FAULT.format(reason=f"Not recorded: {name}")
        return 200, path.read_text()

    return respond


def _writes(sent: list[str]) -> list[str]:
    return [envelope for envelope in sent if ":Set" in _body(envelope)[:40]]


# --- builders ---------------------------------------------------------------------------

_MULTICAST = {
    "address_type": "IPv4",
    "address": "224.1.0.0",
    "port": 40000,
    "ttl": 64,
    "auto_start": True,
}
_MULTICAST_XML = (
    "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>224.1.0.0"
    "</tt:IPv4Address></tt:Address><tt:Port>40000</tt:Port><tt:TTL>64</tt:TTL>"
    "<tt:AutoStart>true</tt:AutoStart></tt:Multicast>"
)


def test_media1_encoder_writes_the_multicast_it_is_given() -> None:
    body = envelopes.media_set_video_encoder_configuration(
        token="VE0",
        name="main",
        encoding="H264",
        width=1920,
        height=1080,
        quality=4,
        fps=25,
        bitrate_kbps=4096,
        gop=50,
        h264_profile="High",
        encoding_interval=2,
        multicast=_MULTICAST,
        guaranteed_frame_rate=True,
        session_timeout="PT90S",
    )
    assert '<trt:Configuration token="VE0" GuaranteedFrameRate="true">' in body
    assert "<tt:EncodingInterval>2</tt:EncodingInterval>" in body
    assert (
        "<tt:H264><tt:GovLength>50</tt:GovLength><tt:H264Profile>High</tt:H264Profile></tt:H264>"
        f"{_MULTICAST_XML}<tt:SessionTimeout>PT90S</tt:SessionTimeout>"
    ) in body


def test_media1_encoder_writes_mpeg4_under_its_media1_name() -> None:
    body = envelopes.media_set_video_encoder_configuration(
        token="VE0",
        name="main",
        encoding="MPV4-ES",
        width=640,
        height=480,
        quality=3,
        fps=None,
        bitrate_kbps=None,
        gop=30,
    )
    assert "<tt:Encoding>MPEG4</tt:Encoding>" in body
    assert "<tt:MPEG4><tt:GovLength>30</tt:GovLength><tt:Mpeg4Profile>SP" in body
    assert "RateControl" not in body


def test_media1_rate_control_needs_both_limits() -> None:
    with pytest.raises(ValueError, match="together"):
        envelopes.media_set_video_encoder_configuration(
            token="VE0",
            name="main",
            encoding="H264",
            width=1,
            height=1,
            quality=1,
            fps=None,
            bitrate_kbps=512,
        )


def test_audio_encoder_translates_media2_codec_names_for_media1() -> None:
    body = envelopes.media_set_audio_encoder_configuration(
        token="A0",
        name="audio",
        encoding="PCMU",
        bitrate_kbps=64,
        sample_rate=8,
        multicast=_MULTICAST,
    )
    assert "<tt:Encoding>G711</tt:Encoding>" in body
    assert _MULTICAST_XML in body
    assert "MP4A-LATM" not in envelopes.media_set_audio_encoder_configuration(
        token="A0", name="a", encoding="MP4A-LATM", bitrate_kbps=64, sample_rate=16
    )


def test_metadata_configuration_writes_its_event_filter_in_schema_order() -> None:
    body = envelopes.media_set_metadata_configuration(
        token="M0",
        name="meta",
        ptz_status=True,
        events=True,
        events_topic_filter="tns1:RuleEngine//.",
    )
    assert (
        "</tt:PTZStatus><tt:Events><tt:Filter><wsnt:TopicExpression "
        'Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">'
        "tns1:RuleEngine//.</wsnt:TopicExpression></tt:Filter></tt:Events>"
        "<tt:Analytics>true</tt:Analytics><tt:Multicast>"
    ) in body
    assert "<tt:Events/>" in envelopes.media_set_metadata_configuration(
        token="M0", name="meta", events=True
    )
    assert "Events" not in envelopes.media_set_metadata_configuration(token="M0", name="meta")


def test_video_source_configuration_sends_use_count_as_the_required_element() -> None:
    body = envelopes.media_set_video_source_configuration(
        token="VSC0",
        name="video",
        source_token="VS0",
        x=0,
        y=0,
        width=1920,
        height=1080,
        use_count=3,
        rotate_degree=90,
    )
    assert 'UseCount="' not in body
    assert (
        '<trt:Configuration token="VSC0"><tt:Name>video</tt:Name><tt:UseCount>3</tt:UseCount>'
        "<tt:SourceToken>VS0</tt:SourceToken>"
    ) in body
    assert "<tt:Rotate><tt:Mode>ON</tt:Mode><tt:Degree>90</tt:Degree></tt:Rotate>" in body


def test_imaging_settings_nest_each_extension_at_its_schema_depth() -> None:
    body = envelopes.imaging_set_settings(
        video_source_token="VS0",
        exposure_mode="MANUAL",
        exposure_min_iris=1,
        exposure_iris=2,
        focus_auto_mode="MANUAL",
        focus_near_limit=0.5,
        image_stabilization_mode="ON",
        ir_cut_auto_boundary_type="ToOn",
        ir_cut_auto_boundary_offset=0.1,
        tone_compensation_mode="AUTO",
        defogging_mode="OFF",
        noise_reduction_level=0.5,
    )
    assert (
        "<tt:Exposure><tt:Mode>MANUAL</tt:Mode><tt:MinIris>1</tt:MinIris><tt:Iris>2</tt:Iris>"
        "</tt:Exposure><tt:Focus><tt:AutoFocusMode>MANUAL</tt:AutoFocusMode>"
        "<tt:NearLimit>0.5</tt:NearLimit></tt:Focus>"
    ) in body
    assert (
        "<tt:Extension><tt:ImageStabilization><tt:Mode>ON</tt:Mode></tt:ImageStabilization>"
        "<tt:Extension><tt:IrCutFilterAutoAdjustment><tt:BoundaryType>ToOn</tt:BoundaryType>"
        "<tt:BoundaryOffset>0.1</tt:BoundaryOffset></tt:IrCutFilterAutoAdjustment>"
        "<tt:Extension><tt:ToneCompensation><tt:Mode>AUTO</tt:Mode></tt:ToneCompensation>"
        "<tt:Defogging><tt:Mode>OFF</tt:Mode></tt:Defogging>"
        "<tt:NoiseReduction><tt:Level>0.5</tt:Level></tt:NoiseReduction>"
        "</tt:Extension></tt:Extension></tt:Extension>"
    ) in body
    assert "Extension" not in envelopes.imaging_set_settings(
        video_source_token="VS0", brightness=50
    )


def test_imaging_setting_names_cover_every_builder_argument() -> None:
    accepted = set(inspect.signature(envelopes.imaging_set_settings).parameters)
    assert accepted - {"video_source_token", "force_persistence"} == updates.IMAGING_SETTING_NAMES


# --- setters keep what they were not asked to change ------------------------------------


def test_media1_encoder_setter_keeps_the_device_multicast_and_session_timeout() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.set_video_encoder_configuration(
        token="00001",
        name="sub",
        encoding="H264",
        width=704,
        height=576,
        quality=4,
        fps=25,
        bitrate_kbps=512,
        gop=25,
    )
    write = _writes(sent)[0]
    assert "<tt:IPv4Address>224.1.0.1</tt:IPv4Address>" in write
    assert "<tt:Port>40008</tt:Port>" in write
    assert "0.0.0.0" not in write
    assert "<tt:SessionTimeout>PT60S</tt:SessionTimeout>" in write


def test_media1_encoder_setter_reads_nothing_when_told_everything() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.set_video_encoder_configuration(
        token="00001",
        name="sub",
        encoding="H264",
        width=704,
        height=576,
        quality=4,
        multicast=_MULTICAST,
        session_timeout="PT30S",
        encoding_interval=1,
    )
    assert len(sent) == 1


def test_audio_encoder_setter_keeps_the_device_multicast() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.set_audio_encoder_configuration(
        token="00000", name="audio", encoding="G711", bitrate_kbps=32, sample_rate=8
    )
    write = _writes(sent)[0]
    assert "<tt:Port>40002</tt:Port>" in write
    assert "<tt:UseCount>1</tt:UseCount>" in write


def test_metadata_setter_keeps_streaming_the_events_it_streamed() -> None:
    current = (
        "<GetMetadataConfigurationsResponse><Configurations token='M0'><Name>meta</Name>"
        "<UseCount>1</UseCount><Events><Filter><TopicExpression>tns1:VideoSource//."
        "</TopicExpression></Filter></Events><Analytics>false</Analytics>"
        "<Multicast><Address><Type>IPv4</Type><IPv4Address>239.0.0.9</IPv4Address></Address>"
        "<Port>5000</Port><TTL>2</TTL><AutoStart>false</AutoStart></Multicast>"
        "<SessionTimeout>PT30S</SessionTimeout></Configurations>"
        "</GetMetadataConfigurationsResponse>"
    )
    client = make_client()
    sent = stub(client, lambda e: (200, current if "GetMetadata" in e else "<Ok/>"))
    client.set_metadata_configuration(token="M0", name="meta", analytics=True)
    write = sent[-1]
    assert "tns1:VideoSource//.</wsnt:TopicExpression>" in write
    assert "<tt:IPv4Address>239.0.0.9</tt:IPv4Address>" in write
    assert "<tt:SessionTimeout>PT30S</tt:SessionTimeout>" in write
    assert "<tt:Analytics>true</tt:Analytics>" in write


def test_video_source_rotation_keeps_the_crop_and_name() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.set_video_source_rotation(configuration_token="00000", mode="ON", degree=180)
    write = _writes(sent)[0]
    assert '<tt:Bounds x="22" y="0" width="2048" height="1536"/>' in write
    assert "<tt:Name>VideoSourceConfig_Channel1</tt:Name><tt:UseCount>5</tt:UseCount>" in write
    assert "<tt:Degree>180</tt:Degree>" in write


def test_video_source_setter_without_a_size_keeps_the_current_bounds() -> None:
    """The old defaults wrote a 0x0 crop when only the rotation was meant to change."""
    client = make_client()
    sent = stub(client, cpplus())
    client.set_video_source_configuration(
        token="00000", name="v", source_token="00000", rotate="OFF"
    )
    assert '<tt:Bounds x="22" y="0" width="2048" height="1536"/>' in _writes(sent)[0]


def test_video_source_rotation_of_an_unknown_configuration_is_refused() -> None:
    client = make_client()
    stub(client, cpplus())
    with pytest.raises(OnvifCapabilityMissingError):
        client.set_video_source_rotation(configuration_token="nope", mode="OFF")


# --- update_video_encoder_configuration -------------------------------------------------


def test_changing_the_bit_rate_keeps_everything_else_on_media2() -> None:
    """The CP Plus main stream is CBR H.265 with multicast: all of it must survive."""
    client = make_client()
    sent = stub(client, cpplus())
    applied = client.update_video_encoder_configuration(
        configuration_token="00000", bitrate_kbps=2048
    )
    assert applied["service"] == "media2"
    write = _writes(sent)[0]
    assert write.count("<trt2:SetVideoEncoderConfiguration>") == 1
    assert '<trt2:Configuration token="00000" GovLength="50" Profile="Main">' in write
    assert '<tt:RateControl ConstantBitRate="true">' in write
    assert "<tt:FrameRateLimit>25</tt:FrameRateLimit><tt:BitrateLimit>2048" in write
    assert "<tt:IPv4Address>224.1.0.0</tt:IPv4Address><" in write
    assert "<tt:Quality>4</tt:Quality>" in write
    assert "<tt:Encoding>H265</tt:Encoding>" in write


async def test_async_changing_the_bit_rate_keeps_everything_else_on_media2() -> None:
    client = make_async_client()
    sent = stub_async(client, cpplus())
    applied = await client.update_video_encoder_configuration(
        configuration_token="00000", bitrate_kbps=2048, constant_bitrate=False
    )
    assert applied["service"] == "media2"
    assert '<tt:RateControl ConstantBitRate="false">' in _writes(sent)[0]


def test_a_value_the_encoder_does_not_offer_is_refused_before_anything_is_sent() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    with pytest.raises(OnvifValidationError) as caught:
        client.update_video_encoder_configuration(
            configuration_token="00000", bitrate_kbps=9000, frame_rate=27.5, width=3840
        )
    assert set(caught.value.errors) == {"bitrate_kbps", "frame_rate", "resolution"}
    assert "512 to 5632" in caught.value.errors["bitrate_kbps"][0]
    assert caught.value.code == "onvif_invalid_settings"
    assert _writes(sent) == []


def test_an_encoding_the_encoder_does_not_offer_is_refused() -> None:
    client = make_client()
    stub(client, cpplus())
    with pytest.raises(OnvifValidationError, match="JPEG"):
        client.update_video_encoder_configuration(configuration_token="00000", encoding="JPEG")


def test_validation_can_be_skipped_for_a_device_with_wrong_options() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.update_video_encoder_configuration(
        configuration_token="00000", bitrate_kbps=9000, validate=False
    )
    assert "<tt:BitrateLimit>9000</tt:BitrateLimit>" in _writes(sent)[0]


def test_switching_codec_drops_a_profile_the_new_codec_does_not_have() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    client.update_video_encoder_configuration(configuration_token="00002", encoding="H265")
    write = _writes(sent)[0]
    assert "<tt:Encoding>H265</tt:Encoding>" in write
    assert 'Profile="High"' not in write


def test_media2_refusal_falls_back_to_media1_for_h264() -> None:
    client = make_client()
    sent = stub(client, cpplus(refuse_media2_writes=True))
    applied = client.update_video_encoder_configuration(
        configuration_token="00001", bitrate_kbps=1024
    )
    assert applied["service"] == "media"
    media1 = [w for w in _writes(sent) if "<trt:SetVideoEncoderConfiguration>" in w]
    assert len(media1) == 1
    assert "<tt:BitrateLimit>1024</tt:BitrateLimit>" in media1[0]
    assert "<tt:Port>40008</tt:Port>" in media1[0]


def test_media2_refusal_is_final_for_h265_which_media1_cannot_express() -> None:
    client = make_client()
    sent = stub(client, cpplus(refuse_media2_writes=True))
    with pytest.raises(OnvifFaultError):
        client.update_video_encoder_configuration(configuration_token="00000", bitrate_kbps=2048)
    assert not any("<trt:SetVideoEncoderConfiguration>" in w for w in _writes(sent))


def test_an_unknown_encoder_configuration_is_refused() -> None:
    client = make_client()
    stub(client, cpplus())
    with pytest.raises(OnvifCapabilityMissingError, match="nope"):
        client.update_video_encoder_configuration(configuration_token="nope", gop=10)


def test_merged_options_union_media2_answers_across_profiles() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    options = client.get_video_encoder_options_merged(configuration_token="00000")
    assert {block["encoding"] for block in options} == {"H264", "H265"}
    h265 = next(block for block in options if block["encoding"] == "H265")
    assert h265["constant_bitrate_supported"] is True
    assert 25.0 in h265["frame_rates"]
    assert any("<trt2:ProfileToken>MediaProfile00000</trt2:ProfileToken>" in e for e in sent)


# --- the pure helpers -------------------------------------------------------------------


def test_merge_keeps_unchanged_fields_and_the_codec_profile() -> None:
    current = {
        "token": "VE0",
        "name": "main",
        "encoding": "H264",
        "width": 1920,
        "height": 1080,
        "quality": "4.0",
        "fps_limit": 25,
        "bitrate_kbps": 4096,
        "gop": 50,
        "h264_profile": "High",
        "constant_bitrate": True,
        "multicast": _MULTICAST,
        "use_count": "2",
    }
    merged = updates.merge_video_encoder(current, {"bitrate_kbps": 1024, "gop": None})
    assert merged["bitrate_kbps"] == 1024
    assert merged["gop"] == 50
    assert merged["profile"] == "High"
    assert merged["frame_rate"] == 25.0
    assert merged["quality"] == 4.0
    assert merged["constant_bitrate"] is True
    assert merged["multicast"] == _MULTICAST
    assert merged["use_count"] == 2
    assert updates.merge_video_encoder(current, {"encoding": "HEVC"})["profile"] == ""
    assert (
        updates.merge_video_encoder(current, {"constant_bitrate": False})["constant_bitrate"]
        is False
    )


def test_check_only_judges_what_changed_unless_the_codec_did() -> None:
    options = [
        {
            "encoding": "H264",
            "resolutions": [{"width": 1920, "height": 1080}],
            "gop": {"min": 1, "max": 30},
            "bitrate_kbps": {"min": 256, "max": 8192},
            "profiles": ["Main"],
        }
    ]
    merged = updates.merge_video_encoder(
        {"encoding": "H264", "width": 1920, "height": 1080, "gop": 50}, {"bitrate_kbps": 512}
    )
    assert updates.check_video_encoder(merged, options, changed={"bitrate_kbps"}) == {}
    assert "gop" in updates.check_video_encoder(merged, options)
    assert updates.check_video_encoder(merged, [], changed={"gop"}) == {}
    assert updates.check_video_encoder(merged, options, changed={"encoding"}).keys() == {"gop"}


def test_fill_imaging_modes_takes_the_mode_each_block_needs_from_the_device() -> None:
    current = {"Exposure": {"mode": "MANUAL"}, "Focus": {"auto_focus_mode": "AUTO"}}
    filled = updates.fill_imaging_modes(
        {"exposure_max_time": 33333, "focus_near_limit": 1.0, "ir_cut_auto_boundary_offset": 0.2},
        current,
    )
    assert filled["exposure_mode"] == "MANUAL"
    assert filled["focus_auto_mode"] == "AUTO"
    assert filled["ir_cut_auto_boundary_type"] == "Common"
    assert "backlight_compensation_mode" not in filled
    assert updates.fill_imaging_modes({"exposure_mode": "AUTO"}, current) == {
        "exposure_mode": "AUTO"
    }


def test_check_imaging_against_the_recorded_options() -> None:
    options = {
        "brightness": {"min": 0.0, "max": 100.0},
        "exposure": {"modes": ["MANUAL"], "iris": {"min": 0.0, "max": 1.0}},
        "ir_cut_filter_modes": [],
    }
    assert updates.check_imaging({"brightness": 50, "exposure_iris": 0.5}, options) == {}
    problems = updates.check_imaging(
        {"brightness": 150, "exposure_mode": "AUTO", "sharpness": 3, "ir_cut_filter": "ON"},
        options,
    )
    assert problems == {
        "brightness": ["Must be from 0 to 100."],
        "sharpness": ["The device does not offer this setting."],
        "exposure_mode": ["Must be one of MANUAL."],
        "ir_cut_filter": ["The device does not offer this setting."],
    }
    assert updates.check_imaging({"brightness": 150}, {}) == {}


# --- imaging_update_settings ------------------------------------------------------------


def test_imaging_update_fills_in_the_exposure_mode_the_schema_requires() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    applied = client.imaging_update_settings(video_source_token="00000", exposure_iris=0.5)
    assert applied == {"exposure_iris": 0.5, "exposure_mode": "MANUAL"}
    assert (
        "<tt:Exposure><tt:Mode>MANUAL</tt:Mode><tt:Iris>0.5</tt:Iris></tt:Exposure>"
        in _writes(sent)[0]
    )


async def test_async_imaging_update_validates_against_the_device_options() -> None:
    client = make_async_client()
    sent = stub_async(client, cpplus())
    with pytest.raises(OnvifValidationError) as caught:
        await client.imaging_update_settings(video_source_token="00000", brightness=101)
    assert "brightness" in caught.value.errors
    assert _writes(sent) == []


def test_imaging_update_rejects_unknown_settings_and_skips_empty_changes() -> None:
    client = make_client()
    sent = stub(client, cpplus())
    with pytest.raises(TypeError, match="brightnes"):
        client.imaging_update_settings(video_source_token="00000", brightnes=10)
    assert client.imaging_update_settings(video_source_token="00000", brightness=None) == {}
    assert sent == []


# --- change_password --------------------------------------------------------------------

_USERS = (
    "<GetUsersResponse><User><Username>Admin</Username><UserLevel>Administrator</UserLevel>"
    "</User><User><Username>viewer</Username><UserLevel>User</UserLevel></User>"
    "</GetUsersResponse>"
)


def test_changing_the_clients_own_password_keeps_its_level_and_the_client_working() -> None:
    client = make_client(credentials=OnvifCredentials("admin", "old"))
    sent = stub(client, lambda e: (200, _USERS if "GetUsers" in e else "<SetUserResponse/>"))
    assert client.change_password(new_password="n3w-Secret") == "Admin"
    set_user = next(e for e in sent if "<tds:SetUser>" in e)
    assert "<tt:Username>Admin</tt:Username>" in set_user
    assert "<tt:UserLevel>Administrator</tt:UserLevel>" in set_user
    assert client.credentials.password == "n3w-Secret"


def test_changing_another_accounts_password_leaves_the_client_alone() -> None:
    client = make_client(credentials=OnvifCredentials("admin", "old"))
    stub(client, lambda e: (200, _USERS if "GetUsers" in e else "<SetUserResponse/>"))
    client.change_password(new_password="x", username="VIEWER")
    assert client.credentials.password == "old"


async def test_async_changing_an_unknown_account_is_refused() -> None:
    client = make_async_client(credentials=OnvifCredentials("admin", "old"))
    sent = stub_async(client, _USERS)
    with pytest.raises(OnvifValidationError, match="ghost"):
        await client.change_password(new_password="x", username="ghost")
    assert not any("SetUser" in e for e in sent)


# --- the async client takes the same paths ----------------------------------------------


async def test_async_media2_refusal_falls_back_to_media1_keeping_multicast() -> None:
    client = make_async_client()
    sent = stub_async(client, cpplus(refuse_media2_writes=True))
    applied = await client.update_video_encoder_configuration(
        configuration_token="00001", bitrate_kbps=1024
    )
    assert applied["service"] == "media"
    media1 = next(w for w in _writes(sent) if "<trt:SetVideoEncoderConfiguration>" in w)
    assert "<tt:Port>40008</tt:Port>" in media1


async def test_async_setters_keep_what_they_were_not_told() -> None:
    client = make_async_client()
    sent = stub_async(client, cpplus())
    await client.set_audio_encoder_configuration(
        token="00000", name="audio", encoding="PCMU", bitrate_kbps=32, sample_rate=8
    )
    await client.set_video_source_rotation(configuration_token="00000", mode="OFF")
    await client.set_video_source_configuration(
        token="00000", name="v", source_token="00000", width=1920, height=1080
    )
    audio, rotation, crop = _writes(sent)
    assert "<tt:Port>40002</tt:Port>" in audio and "<tt:Encoding>G711</tt:Encoding>" in audio
    assert '<tt:Bounds x="22" y="0" width="2048" height="1536"/>' in rotation
    assert '<tt:Bounds x="0" y="0" width="1920" height="1080"/>' in crop


async def test_async_metadata_setter_keeps_the_event_filter() -> None:
    current = (
        "<GetMetadataConfigurationsResponse><Configurations token='M0'><Name>meta</Name>"
        "<UseCount>1</UseCount><Events/><Analytics>false</Analytics>"
        "<SessionTimeout>PT30S</SessionTimeout></Configurations>"
        "</GetMetadataConfigurationsResponse>"
    )
    client = make_async_client()
    sent = stub_async(client, lambda e: (200, current if "GetMetadata" in e else "<Ok/>"))
    await client.set_metadata_configuration(token="M0", name="meta", events_topic_filter="")
    assert "<tt:Events/>" in sent[-1]


async def test_async_an_unknown_encoder_or_source_is_refused() -> None:
    client = make_async_client()
    stub_async(client, cpplus())
    with pytest.raises(OnvifCapabilityMissingError):
        await client.update_video_encoder_configuration(configuration_token="nope", gop=10)
    with pytest.raises(OnvifCapabilityMissingError):
        await client.set_video_source_rotation(configuration_token="nope", mode="OFF")
