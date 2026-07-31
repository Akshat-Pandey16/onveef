"""Tests for the operations added to close the media-configuration and device gaps."""

from __future__ import annotations

import pytest

from conftest import make_async_client, make_client, stub, stub_async
from onveef import envelopes, parsers

_VIDEO_SOURCE_CONFIGS = """
<GetVideoSourceConfigurationsResponse>
  <Configurations token="VSC0">
    <Name>VideoSourceConfig</Name>
    <UseCount>2</UseCount>
    <SourceToken>VS0</SourceToken>
    <Bounds x="0" y="0" width="2688" height="1520"/>
    <Extension><Rotate><Mode>OFF</Mode><Degree>0</Degree></Rotate></Extension>
  </Configurations>
</GetVideoSourceConfigurationsResponse>
"""

_VIDEO_SOURCE_OPTIONS = """
<GetVideoSourceConfigurationOptionsResponse>
  <Options>
    <BoundsRange>
      <XRange><Min>0</Min><Max>0</Max></XRange>
      <YRange><Min>0</Min><Max>0</Max></YRange>
      <WidthRange><Min>2688</Min><Max>2688</Max></WidthRange>
      <HeightRange><Min>1520</Min><Max>1520</Max></HeightRange>
    </BoundsRange>
    <VideoSourceTokensAvailable>VS0</VideoSourceTokensAvailable>
    <Extension><Rotate><Mode>OFF</Mode><Mode>ON</Mode></Rotate></Extension>
  </Options>
</GetVideoSourceConfigurationOptionsResponse>
"""


def test_get_video_source_configurations() -> None:
    client = make_client()
    sent = stub(client, _VIDEO_SOURCE_CONFIGS)
    configs = client.get_video_source_configurations()
    assert "<trt:GetVideoSourceConfigurations/>" in sent[0]
    assert configs[0]["token"] == "VSC0"
    assert configs[0]["source_token"] == "VS0"
    assert configs[0]["use_count"] == 2
    assert configs[0]["bounds"] == {"x": 0, "y": 0, "width": 2688, "height": 1520}
    assert configs[0]["rotate"] == "OFF"


def test_get_video_source_configuration_options() -> None:
    client = make_client()
    sent = stub(client, _VIDEO_SOURCE_OPTIONS)
    options = client.get_video_source_configuration_options(configuration_token="VSC0")
    assert "<trt:ConfigurationToken>VSC0</trt:ConfigurationToken>" in sent[0]
    assert options["video_source_tokens"] == ["VS0"]
    assert options["bounds_range"]["width"] == {"min": 2688, "max": 2688}
    assert options["rotate_modes"] == ["OFF", "ON"]


def test_set_video_source_configuration_emits_bounds_and_rotation() -> None:
    client = make_client()
    sent = stub(client, "<SetVideoSourceConfigurationResponse/>")
    client.set_video_source_configuration(
        token="VSC0", name="main", source_token="VS0", width=1920, height=1080, rotate="ON"
    )
    assert '<tt:Bounds x="0" y="0" width="1920" height="1080"/>' in sent[0]
    assert "<tt:Mode>ON</tt:Mode>" in sent[0]
    assert "<trt:ForcePersistence>true</trt:ForcePersistence>" in sent[0]


def test_set_video_source_configuration_omits_rotation_when_unset() -> None:
    body = envelopes.media_set_video_source_configuration(
        token="T", name="n", source_token="S", x=0, y=0, width=1, height=1
    )
    assert "Rotate" not in body


def test_get_profile_requires_media1() -> None:
    client = make_client()
    sent = stub(
        client,
        '<GetProfileResponse><Profile token="P0"><Name>main</Name></Profile></GetProfileResponse>',
    )
    profile = client.get_profile(profile_token="P0")
    assert "<trt:ProfileToken>P0</trt:ProfileToken>" in sent[0]
    assert profile["token"] == "P0"


def test_get_compatible_video_encoder_configurations() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetCompatibleVideoEncoderConfigurationsResponse>"
        '<Configurations token="VEC1"><Name>enc</Name><Encoding>H264</Encoding></Configurations>'
        "</GetCompatibleVideoEncoderConfigurationsResponse>",
    )
    configs = client.get_compatible_video_encoder_configurations(profile_token="P0")
    assert "GetCompatibleVideoEncoderConfigurations" in sent[0]
    assert configs[0]["token"] == "VEC1"


def test_get_audio_encoder_configuration_options() -> None:
    client = make_client()
    stub(
        client,
        "<GetAudioEncoderConfigurationOptionsResponse><Options>"
        "<Encoding>G711</Encoding>"
        "<BitrateList><Items>64</Items><Items>128</Items></BitrateList>"
        "<SampleRateList><Items>8</Items></SampleRateList>"
        "</Options></GetAudioEncoderConfigurationOptionsResponse>",
    )
    options = client.get_audio_encoder_configuration_options()
    assert options[0]["encoding"] == "G711"
    assert options[0]["bitrate_list"] == [64, 128]
    assert options[0]["sample_rate_list"] == [8]


def test_guaranteed_number_of_video_encoder_instances() -> None:
    client = make_client()
    stub(
        client,
        "<GetGuaranteedNumberOfVideoEncoderInstancesResponse>"
        "<TotalNumber>4</TotalNumber><H264>2</H264>"
        "</GetGuaranteedNumberOfVideoEncoderInstancesResponse>",
    )
    result = client.get_guaranteed_number_of_video_encoder_instances(configuration_token="VSC0")
    assert result["total"] == 4
    assert result["h264"] == 2
    assert result["jpeg"] is None


def test_media2_masks_round_trip() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetMasksResponse>"
        '<Masks token="M0"><ConfigurationToken>VSC0</ConfigurationToken>'
        "<Type>Blurred</Type><Enabled>true</Enabled>"
        '<Polygon><Point x="0.1" y="0.2"/><Point x="0.3" y="0.4"/></Polygon>'
        "</Masks></GetMasksResponse>",
    )
    masks = client.media2_get_masks(configuration_token="VSC0")
    assert "<trt2:ConfigurationToken>VSC0</trt2:ConfigurationToken>" in sent[0]
    assert masks[0]["token"] == "M0"
    assert masks[0]["enabled"] is True
    assert masks[0]["polygon"][0] == {"x": 0.1, "y": 0.2}

    sent2 = stub(client, "<DeleteMaskResponse/>")
    client.media2_delete_mask(token="M0")
    assert "<trt2:Token>M0</trt2:Token>" in sent2[0]


def test_storage_configurations() -> None:
    client = make_client()
    stub(
        client,
        "<GetStorageConfigurationsResponse>"
        '<StorageConfigurations token="ST0"><Data>'
        "<Type>NFS</Type><LocalPath>/mnt/rec</LocalPath>"
        "<StorageUri>nfs://10.0.0.2/rec</StorageUri>"
        "<User><UserName>store</UserName><Password>pw</Password></User>"
        "</Data></StorageConfigurations></GetStorageConfigurationsResponse>",
    )
    storage = client.get_storage_configurations()
    assert storage[0]["token"] == "ST0"
    assert storage[0]["type"] == "NFS"
    assert storage[0]["storage_uri"] == "nfs://10.0.0.2/rec"
    assert storage[0]["user"]["username"] == "store"


def test_endpoint_reference() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetEndpointReferenceResponse><GUID>urn:uuid:abc</GUID></GetEndpointReferenceResponse>",
    )
    assert client.get_endpoint_reference() == "urn:uuid:abc"
    assert "<tds:GetEndpointReference/>" in sent[0]


def test_imaging_move_options() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetMoveOptionsResponse><MoveOptions><Continuous>"
        "<Speed><Min>-1.0</Min><Max>1.0</Max></Speed>"
        "</Continuous></MoveOptions></GetMoveOptionsResponse>",
    )
    options = client.imaging_get_move_options(video_source_token="VS0")
    assert "<timg:VideoSourceToken>VS0</timg:VideoSourceToken>" in sent[0]
    assert "Continuous" in options


def test_recording_options() -> None:
    client = make_client()
    sent = stub(
        client,
        "<GetRecordingOptionsResponse><Options><Job><Spare>2</Spare></Job>"
        "<Track><SpareTotal>4</SpareTotal></Track></Options></GetRecordingOptionsResponse>",
    )
    options = client.get_recording_options(recording_token="R0")
    assert "<trc:RecordingToken>R0</trc:RecordingToken>" in sent[0]
    assert options["Job"]["Spare"] == "2"


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        ("start_firmware_upgrade", "StartFirmwareUpgrade"),
        ("start_system_restore", "StartSystemRestore"),
    ],
)
def test_upload_target_operations(method: str, operation: str) -> None:
    client = make_client()
    sent = stub(
        client,
        f"<{operation}Response><UploadUri>http://192.168.1.5/upload</UploadUri>"
        f"<UploadDelay>PT10S</UploadDelay><ExpectedDownTime>PT3M</ExpectedDownTime>"
        f"</{operation}Response>",
    )
    result = getattr(client, method)()
    assert f"<tds:{operation}/>" in sent[0]
    assert result["upload_uri"] == "http://192.168.1.5/upload"
    assert result["expected_down_time"] == "PT3M"


def test_normalized_encoder_options() -> None:
    client = make_client()
    stub(
        client,
        "<GetVideoEncoderConfigurationOptionsResponse><Options>"
        "<H264><ResolutionsAvailable><Width>1920</Width><Height>1080</Height>"
        "</ResolutionsAvailable><GovLengthRange><Min>1</Min><Max>60</Max></GovLengthRange>"
        "<H264ProfilesSupported>Main</H264ProfilesSupported></H264>"
        "</Options></GetVideoEncoderConfigurationOptionsResponse>",
    )
    options = client.get_video_encoder_options_normalized(configuration_token="VEC0")
    assert options[0]["encoding"] == "H264"
    assert {"width": 1920, "height": 1080} in options[0]["resolutions"]
    assert options[0]["profiles"] == ["Main"]


def test_parse_video_source_configurations_handles_empty() -> None:
    assert parsers.parse_video_source_configurations("<nope/>") == []
    assert parsers.parse_video_source_configuration_options("<nope/>") == {}
    assert parsers.parse_masks("<nope/>") == []
    assert parsers.parse_storage_configurations("<nope/>") == []
    assert parsers.parse_upload_target("") == {}
    assert parsers.parse_encoder_instances("") == {}


async def test_async_parity_for_new_operations() -> None:
    client = make_async_client()
    sent = stub_async(client, _VIDEO_SOURCE_CONFIGS)
    configs = await client.get_video_source_configurations()
    assert configs[0]["token"] == "VSC0"
    assert "GetVideoSourceConfigurations" in sent[0]
