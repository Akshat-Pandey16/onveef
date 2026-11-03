from __future__ import annotations

import pathlib

import pytest

from onveef import parsers

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read(rel: str) -> str:
    return (_FIXTURES / rel).read_text(encoding="utf-8")


def test_hikvision_device_information() -> None:
    info = parsers.parse_device_information(_read("hikvision/GetDeviceInformation.xml"))
    assert info["Manufacturer"] == "HIKVISION"
    assert info["Model"] == "DS-2CD2085FWD-I"
    assert info["FirmwareVersion"].startswith("V5.6.3")


@pytest.mark.parametrize(
    ("fixture", "expected_encoding"),
    [
        ("hikvision/GetProfiles.xml", "H264"),
        ("dahua/GetProfiles.xml", "H265"),
    ],
)
def test_profiles_across_vendors(fixture: str, expected_encoding: str) -> None:
    profiles = parsers.parse_profiles(_read(fixture))
    assert profiles, f"{fixture} produced no profiles"
    profile = profiles[0]
    assert profile["token"]
    encoder = profile["video_encoder"]
    assert encoder["encoding"] == expected_encoding
    assert encoder["width"] and encoder["height"]
    assert encoder["fps_limit"] is not None
    assert encoder["gop"] == 50


def test_axis_system_datetime_parses_to_fields() -> None:
    dt = parsers.parse_system_datetime(_read("axis/GetSystemDateAndTime.xml"))
    assert dt["date_time_type"] == "NTP"
    assert dt["daylight_savings"] is True
    assert dt["UTCDateTime"]["year"] == 2026
    assert dt["UTCDateTime"]["hour"] == 10


def test_reolink_stream_uri() -> None:
    uri = parsers.parse_stream_uri(_read("reolink/GetStreamUri.xml"))
    assert uri == "rtsp://192.168.1.30:554/h264Preview_01_main"


# --- CP Plus CP-UNP-D2521L10-DAQ (Dahua OEM PTZ), a real capture -------------------------
# Recorded read-only and scrubbed (serial and hardware id redacted). The camera answers
# over Media1 and Media2 differently, which is the point: its H.265 main stream cannot be
# expressed in Media1, so Media1 hands back a stub configuration for it.


def test_cpplus_media2_encoder_keeps_what_a_write_must_send_back() -> None:
    main = parsers.parse_video_encoder_configurations(
        _read("cpplus/Media2-GetVideoEncoderConfigurations.xml")
    )[0]
    assert (main["encoding"], main["width"], main["height"]) == ("H265", 1920, 1080)
    assert (main["gop"], main["profile"], main["frame_rate"]) == (50, "Main", 25.0)
    assert main["constant_bitrate"] is True
    assert main["multicast"] == {
        "address_type": "IPv4",
        "address": "224.1.0.0",
        "port": 40000,
        "ttl": 64,
        "auto_start": False,
    }


def test_cpplus_media1_cannot_describe_its_h265_stream() -> None:
    configs = parsers.parse_video_encoder_configurations(
        _read("cpplus/GetVideoEncoderConfigurations.xml")
    )
    assert configs[0]["encoding"] == ""
    assert "width" not in configs[0]
    sub = configs[1]
    assert (sub["encoding"], sub["gop"], sub["profile"]) == ("H264", 25, "Main")
    assert sub["multicast"]["port"] == 40008
    assert sub["session_timeout"] == "PT60S"


def test_cpplus_media2_options_list_discrete_rates_and_cbr() -> None:
    options = {
        block["encoding"]: block
        for block in parsers.parse_video_encoder_options_normalized(
            _read("cpplus/Media2-GetVideoEncoderConfigurationOptions-00000.xml")
        )
    }
    assert set(options) == {"H264", "H265"}
    h264 = options["H264"]
    assert h264["frame_rates"] == [float(rate) for rate in range(1, 26)]
    assert h264["constant_bitrate_supported"] is True
    assert h264["bitrate_kbps"] == {"min": 512.0, "max": 5632.0}
    assert h264["profiles"] == ["Main", "Baseline", "High"]
    assert options["H265"]["profiles"] == ["Main"]


def test_cpplus_media1_options_carry_the_encoding_interval() -> None:
    [h264] = parsers.parse_video_encoder_options_normalized(
        _read("cpplus/GetVideoEncoderConfigurationOptions-00000.xml")
    )
    assert h264["encoding_interval"] == {"min": 1.0, "max": 1.0}
    assert h264["frame_rates"] == []


@pytest.mark.parametrize("prefix", ["", "Media2-"])
def test_cpplus_profiles_name_their_audio_source(prefix: str) -> None:
    profile = parsers.parse_profiles(_read(f"cpplus/{prefix}GetProfiles.xml"))[0]
    assert profile["audio_source"] == {
        "token": "00000",
        "name": "AudioSourceConfig_Channel1",
        "source_token": "00000",
    }
    assert profile["ptz"]["node_token"] == "00000"


def test_cpplus_rotation_options() -> None:
    options = parsers.parse_video_source_configuration_options(
        _read("cpplus/GetVideoSourceConfigurationOptions-00000.xml")
    )
    assert options["rotate_modes"] == ["OFF"]
    assert options["rotate_degrees"] == [0]
    assert options["rotate_reboot"] is False


def test_cpplus_imaging_options_normalised() -> None:
    options = parsers.parse_imaging_options_normalized(_read("cpplus/GetOptions-00000.xml"))
    assert options["brightness"] == {"min": 0.0, "max": 100.0}
    assert options["exposure"]["modes"] == ["MANUAL"]
    assert options["exposure"]["iris"] == {"min": 0.0, "max": 1.0}
    assert options["focus"]["auto_focus_modes"] == ["MANUAL"]
    assert options["wide_dynamic_range"] is None
    assert options["noise_reduction"] is None


def test_cpplus_audio_encoder_keeps_multicast_and_options_read_in_order() -> None:
    [first, *_] = parsers.parse_audio_encoder_configurations(
        _read("cpplus/GetAudioEncoderConfigurations.xml")
    )
    assert (first["encoding"], first["session_timeout"]) == ("G711", "PT60S")
    assert first["multicast"]["port"] == 40002
    options = parsers.parse_audio_encoder_configuration_options(
        _read("cpplus/Media2-GetAudioEncoderConfigurationOptions-00000.xml")
    )
    assert options[0] == {
        "encoding": "MP4A-LATM",
        "bitrate_list": [32, 64, 128, 192, 256],
        "sample_rate_list": [8, 16, 32, 48, 64],
    }
